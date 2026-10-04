"""Cartera: redes de fraude, métricas, importación del historial y exportación a Excel."""
from __future__ import annotations

import io
import tempfile
from pathlib import Path

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for

from evidex.claims import service
from evidex.web.common import LEVEL_TEXT, actor_name, claim_list, cx, log_access, network_components, save_checked

bp = Blueprint("portfolio", __name__)


def _import_file(path: Path, actor: str, name: str):
    from evidex.claims import importer
    rep = importer.import_history(cx.workdir, path, actor=actor, original_name=name)
    return render_template("portfolio/import.html", report=rep, nets=len(network_components()) if not rep.get("error") else 0, active="importar")


@bp.get("/redes")
def networks():
    comps = network_components()
    rings = [c for c in comps if len(c["members"]) >= 3]
    pairs = [c for c in comps if len(c["members"]) == 2]
    return render_template("portfolio/networks.html", comps=comps, rings=rings, pairs=pairs, active="redes",
                           involved=sum(len(c["members"]) for c in comps), total=sum(c["monto"] for c in comps),
                           level_text={"bad": "Derivar", "warn": "Revisión", "ok": "Sin alertas", None: "Sin analizar"})


@bp.get("/metricas")
def metrics_view():
    from evidex.claims.report import RULE_NAMES
    return render_template("portfolio/metrics.html", m=service.metrics(cx.workdir), rule_names=RULE_NAMES, active="metricas")


@bp.route("/importar", methods=["GET", "POST"])
def import_view():
    if request.method == "GET":
        return render_template("portfolio/import.html", report=None, active="importar")
    fs = request.files.get("archivo")
    actor = actor_name() or "importación"
    if not fs or not fs.filename or Path(fs.filename).suffix.lower() not in (".csv", ".xlsx", ".xlsm"):
        flash("Seleccione un archivo CSV o Excel (.xlsx).", "bad")
        return redirect(url_for("portfolio.import_view"))
    with tempfile.TemporaryDirectory() as td:
        path, why = save_checked(fs, Path(td), "historial", "historial.csv")
        if why:
            flash("Archivo rechazado: " + why, "bad")
            return redirect(url_for("portfolio.import_view"))
        return _import_file(path, actor, fs.filename)


@bp.post("/importar/ejemplo")
def import_demo():
    script = service.DEMO_SCRIPT.parent / "make_history_demo.py"
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "historial_demo.csv"
        import subprocess
        import sys
        subprocess.run([sys.executable, str(script), str(path)], check=True, capture_output=True)
        return _import_file(path, "importación de ejemplo", "historial_demo.csv")


@bp.get("/plantilla.csv")
def template_download():
    from evidex.claims import importer
    return send_file(io.BytesIO(importer.template_csv().encode("utf-8")), mimetype="text/csv",
                     as_attachment=True, download_name="plantilla_siniestros.csv")


@bp.get("/exportar/<what>.xlsx")
def export_xlsx(what):
    from evidex.claims import excel
    from datetime import date
    log_access("exporta_excel", what)
    if what == "cola":
        data = excel.queue(claim_list(), LEVEL_TEXT)
    elif what == "redes":
        data = excel.networks(network_components(), LEVEL_TEXT)
    elif what == "metricas":
        from evidex.claims.report import RULE_NAMES
        data = excel.metrics(service.metrics(cx.workdir), RULE_NAMES)
    else:
        abort(404)
    return send_file(io.BytesIO(data), as_attachment=True, download_name=f"evidex_{what}_{date.today():%Y-%m-%d}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
