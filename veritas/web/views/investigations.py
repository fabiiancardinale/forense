"""Expedientes de investigación (peritos) y auditoría de informes."""
from __future__ import annotations

import io
import os
import json
import re
import tempfile
from pathlib import Path

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from veritas.claims import service
from veritas.core import export
from veritas.core.case import Case, sha256_file
from veritas.investigations import dossier as INV
from veritas.web.common import actor_name, cx, dossier_lists, load_dossier, load_settings, log_access

bp = Blueprint("investigations", __name__)


@bp.get("/investigaciones")
def investigations():
    exps, audits = dossier_lists()
    return render_template("investigations/list.html", expedientes=exps, audits=audits, empresa=load_settings().get("empresa", ""), active="inv")


@bp.post("/investigaciones/config")
def inv_settings():
    cfg = load_settings()
    cfg["empresa"] = request.form.get("empresa", "").strip()
    cx.config_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    flash("Configuración guardada.", "ok")
    return redirect(url_for("investigations.investigations"))


@bp.post("/investigaciones/ejemplo")
def inv_demo():
    done = INV.load_demo(cx.workdir)
    flash("Ejemplo ficticio cargado: " + ", ".join(done) if done else "El ejemplo ya estaba cargado.", "info")
    return redirect(url_for("investigations.investigations"))


@bp.route("/investigaciones/nuevo", methods=["GET", "POST"])
def inv_new():
    f = request.form
    if request.method == "GET":
        return render_template("investigations/new.html", f={}, error=None, active="inv_new")
    numero, fecha, actor = f.get("numero", "").strip(), f.get("fecha_ocurrencia", "").strip(), actor_name()
    if not numero or not fecha or not actor:
        return render_template("investigations/new.html", f=f, error="Número de siniestro, fecha y su nombre son obligatorios.", active="inv_new"), 400
    cid = service.case_id(numero)
    if (cx.workdir / cid / "case.json").exists():
        return render_template("investigations/new.html", f=f, error=f"Ya existe un expediente {numero}.", active="inv_new"), 400
    data = {k: f.get(k, "").strip() for k in ("numero", "aseguradora", "tipo", "direccion", "comuna", "vehiculo", "patente",
                                              "rut_asegurado", "descripcion")}
    data["fecha_ocurrencia"] = fecha if len(fecha) > 16 else fecha + ":00"
    data["alertas"] = [x.strip() for x in f.get("alertas", "").splitlines() if x.strip()]
    ivs = [{"declarante": dcl.strip(), "rol": rol.strip(), "fecha": fch.strip(), "texto": txt}
           for dcl, rol, fch, txt in zip(f.getlist("iv_declarante"), f.getlist("iv_rol"), f.getlist("iv_fecha"), f.getlist("iv_texto"))
           if dcl.strip() and txt.strip()]
    with tempfile.TemporaryDirectory() as td:
        saved = []
        for fs in request.files.getlist("docs"):
            if fs and fs.filename:
                dest = Path(td) / (secure_filename(fs.filename) or "documento")
                fs.save(dest)
                saved.append(dest)
        INV.create(cx.workdir, cid, data, ivs, saved, actor=actor)
    flash("Expediente creado y analizado.", "ok")
    return redirect(url_for("investigations.inv_view", cid=cid))


@bp.get("/investigacion/<cid>")
def inv_view(cid):
    log_access("ver_expediente", cid)
    from veritas.investigations import audit as RA
    a = INV.analyze(load_dossier(cid, "investigacion"))
    review = INV.review(a)
    return render_template("investigations/dossier.html", a=a, d=a["data"], cid=cid, review=review, states=INV.STATES,
                           recommendations=INV.RECOMMENDATIONS, matrix=RA.topic_matrix(a["interviews"]), active="inv",
                           answered=sum(1 for r in a["responses"].values() if r.get("estado")))


@bp.post("/investigacion/<cid>/alerta/<int:idx>")
def inv_response(cid, idx):
    case = load_dossier(cid, "investigacion")
    INV.save_response(case, idx, request.form.get("estado", ""), request.form.get("hallazgo", "").strip(),
                      sorted(set(request.form.getlist("evidencia"))), actor_name())
    flash(f"Respuesta a la alerta {idx} guardada.", "ok")
    return redirect(url_for("investigations.inv_view", cid=cid))


@bp.post("/investigacion/<cid>/conclusion")
def inv_conclusion(cid):
    case = load_dossier(cid, "investigacion")
    INV.save_conclusion(case, request.form.get("recomendacion", ""), request.form.get("texto", "").strip(), actor_name())
    flash("Conclusión guardada.", "ok")
    return redirect(url_for("investigations.inv_view", cid=cid))


@bp.get("/investigacion/<cid>/informe")
def inv_report(cid):
    case = load_dossier(cid, "investigacion")
    return INV.build_report(case, INV.analyze(case), load_settings().get("empresa", ""))


@bp.get("/investigacion/<cid>/exportar")
def inv_export(cid):
    case = Case(cx.workdir / cid)
    if not re.fullmatch(r"[\w\-.]+", cid) or not case.meta_path.exists() or case.kind not in ("investigacion", "auditoria"):
        abort(404)
    if case.kind == "investigacion":
        html_doc = INV.build_report(case, INV.analyze(case), load_settings().get("empresa", ""))
    else:
        r = INV.run_audit(case)
        html_doc = INV.audit_page(r)
    fd, tmp = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        export.export_bundle(case, html_doc, Path(tmp))
        data = io.BytesIO(Path(tmp).read_bytes())
    finally:
        os.unlink(tmp)
    return send_file(data, mimetype="application/zip", as_attachment=True, download_name=f"{cid}_veritas.zip")


@bp.post("/auditar")
def audit_upload():
    fs = request.files.get("pdf")
    actor = actor_name() or "revisor"
    if not fs or not fs.filename.lower().endswith(".pdf"):
        flash("Seleccione un informe en PDF.", "bad")
        return redirect(url_for("investigations.investigations"))
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / (secure_filename(fs.filename) or "informe.pdf")
        fs.save(path)
        aid = "AUD-" + sha256_file(path)[:8]
        if (cx.workdir / aid / "case.json").exists():
            flash("Ese informe ya estaba auditado; se muestra el resultado.", "info")
            return redirect(url_for("investigations.audit_view", cid=aid))
        case = INV.create_audit(cx.workdir, aid, path, actor=actor, original_name=fs.filename)
    try:
        r = INV.run_audit(case)
    except Exception as ex:  # PDF escaneado, protegido o con otro formato
        flash(f"No se pudo leer el PDF ({type(ex).__name__}). Si es un escaneo, requiere OCR.", "bad")
        return redirect(url_for("investigations.investigations"))
    case.ledger.append("veritas", "audit_run", fs.filename, INV._audit_counts(r["findings"]))
    case.ledger.seal()
    return redirect(url_for("investigations.audit_view", cid=aid))


@bp.get("/auditoria/<cid>")
def audit_view(cid):
    case = load_dossier(cid, "auditoria")
    r = INV.run_audit(case)
    return render_template("investigations/audit.html", body=INV.audit_html(r), name=r["name"], digest=r["digest"], cid=cid, active="inv")
