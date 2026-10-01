"""Expedientes de investigación (peritos) y auditoría de informes."""
from __future__ import annotations

import io
import os
import json
import tempfile
from pathlib import Path

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from veritas.claims import service
from veritas.core import export
from veritas.core.case import Case, sha256_file
from veritas.investigations import dossier as INV
from veritas.claims import assignment
from veritas.web.common import (actor_name, current_user, cx, dossier_lists, has_perm, load_dossier, load_settings,
                                log_access, send_evidence)

bp = Blueprint("investigations", __name__)


@bp.get("/investigaciones")
def investigations():
    """Expedientes y auditorías. Un perito ve aquí solo los encargos de su empresa ("Mis encargos")."""
    exps, audits = dossier_lists()
    u = current_user()
    perito = bool(u and u["role"] == "perito")
    exps.sort(key=lambda x: (bool(x["delivered"]), x["plazo"] or "9999"))
    return render_template("investigations/list.html", expedientes=exps, audits=audits, perito=perito,
                           empresa=load_settings().get("empresa", ""), active="inv", today=_today_iso())


def _today_iso() -> str:
    from datetime import date
    return date.today().isoformat()


def _open_dossier(cid):
    """Expediente que se puede modificar: visible para el usuario y sin informe final entregado."""
    case = load_dossier(cid, "investigacion")
    if INV.delivered(case):
        flash("El informe final ya se entregó: el expediente está cerrado.", "bad")
        return None
    return case


def _claim_of(dossier_case):
    """Siniestro del que se derivó el expediente (o None si el expediente se creó a mano)."""
    sid = INV.load(dossier_case)["data"].get("siniestro_id")
    claim = Case(cx.workdir / sid) if sid else None
    return claim if claim and claim.meta_path.exists() else None


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
    case = load_dossier(cid, "investigacion")
    a = INV.analyze(case)
    review = INV.review(a)
    claim = _claim_of(case)
    antecedentes = []
    if claim is not None:
        snap = service.snapshot(claim)
        antecedentes = ([{"digest": p["digest"], "title": p["title"], "kind": "foto"} for p in snap["photos"]] +
                        [{"digest": d["digest"], "title": d["title"], "kind": "documento"} for d in snap["docs"]])
    return render_template("investigations/dossier.html", a=a, d=a["data"], cid=cid, review=review, states=INV.STATES,
                           recommendations=INV.RECOMMENDATIONS, matrix=RA.topic_matrix(a["interviews"]), active="inv",
                           answered=sum(1 for r in a["responses"].values() if r.get("estado")),
                           delivered=INV.delivered(case), antecedentes=antecedentes, claim=claim, today=_today_iso())


@bp.post("/investigacion/<cid>/entrevista")
def inv_interview(cid):
    case = _open_dossier(cid)
    if case is not None:
        f = request.form
        try:
            INV.add_interview(case, f.get("declarante", ""), f.get("rol", ""), f.get("fecha", ""), f.get("texto", ""),
                              actor_name() or "perito")
            flash("Entrevista agregada. Veritas la comparó con las demás declaraciones y los documentos.", "ok")
        except ValueError as ex:
            flash(str(ex), "bad")
    return redirect(url_for("investigations.inv_view", cid=cid))


@bp.post("/investigacion/<cid>/documentos")
def inv_document(cid):
    case = _open_dossier(cid)
    if case is not None:
        n = 0
        with tempfile.TemporaryDirectory() as td:
            for fs in request.files.getlist("docs"):
                if fs and fs.filename:
                    dest = Path(td) / (secure_filename(fs.filename) or "documento")
                    fs.save(dest)
                    INV.add_document(case, dest, actor_name() or "perito")
                    n += 1
        flash(f"{n} documento(s) agregado(s)." if n else "Elija al menos un documento.", "ok" if n else "bad")
    return redirect(url_for("investigations.inv_view", cid=cid))


@bp.post("/investigacion/<cid>/entregar")
def inv_deliver(cid):
    """El perito entrega su informe final: el expediente se cierra y el analista lo ve en el caso."""
    case = _open_dossier(cid)
    if case is None:
        return redirect(url_for("investigations.inv_view", cid=cid))
    data = INV.load(case)["data"]
    actor = actor_name() or "perito"
    try:
        INV.deliver(case, actor, data.get("empresa") or load_settings().get("empresa", ""))
    except ValueError as ex:
        flash(str(ex), "bad")
        return redirect(url_for("investigations.inv_view", cid=cid))
    claim = _claim_of(case)
    if claim is not None:
        assignment.mark_delivered(claim, actor, cid)
    log_access("entregar_informe", cid)
    flash("Informe final entregado. El analista del caso ya puede verlo.", "ok")
    return redirect(url_for("investigations.inv_view", cid=cid))


@bp.get("/investigacion/<cid>/antecedente/<digest>")
def inv_file(cid, digest):
    """Fotos y documentos del siniestro, para que el perito los vea sin acceso al resto del caso."""
    claim = _claim_of(load_dossier(cid, "investigacion"))
    if claim is None or digest in claim.excluded():
        abort(404)
    return send_evidence(claim, digest, bool(request.args.get("mini")))


@bp.post("/investigacion/<cid>/alerta/<int:idx>")
def inv_response(cid, idx):
    case = _open_dossier(cid)
    if case is None:
        return redirect(url_for("investigations.inv_view", cid=cid))
    INV.save_response(case, idx, request.form.get("estado", ""), request.form.get("hallazgo", "").strip(),
                      sorted(set(request.form.getlist("evidencia"))), actor_name())
    flash(f"Respuesta a la alerta {idx} guardada.", "ok")
    return redirect(url_for("investigations.inv_view", cid=cid))


@bp.post("/investigacion/<cid>/conclusion")
def inv_conclusion(cid):
    case = _open_dossier(cid)
    if case is None:
        return redirect(url_for("investigations.inv_view", cid=cid))
    INV.save_conclusion(case, request.form.get("recomendacion", ""), request.form.get("texto", "").strip(), actor_name())
    flash("Conclusión guardada.", "ok")
    return redirect(url_for("investigations.inv_view", cid=cid))


@bp.get("/investigacion/<cid>/informe")
def inv_report(cid):
    case = load_dossier(cid, "investigacion")
    if (case.root / "informe_final.html").exists():
        return send_file(case.root / "informe_final.html", mimetype="text/html")
    data = INV.load(case)["data"]
    return INV.build_report(case, INV.analyze(case), data.get("empresa") or load_settings().get("empresa", ""))


@bp.get("/investigacion/<cid>/exportar")
def inv_export(cid):
    kind = "auditoria" if cid.startswith("AUD-") else "investigacion"
    if kind == "auditoria" and not has_perm("investigaciones"):
        abort(404)
    case = load_dossier(cid, kind)
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
