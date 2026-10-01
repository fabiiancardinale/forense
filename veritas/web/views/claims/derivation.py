"""Derivación de las entrevistas a un perito o empresa de peritaje, y su informe final."""
from __future__ import annotations

from flask import abort, flash, redirect, request, send_file, url_for

from veritas.claims import assignment, service
from veritas.web.common import actor_name, cx, load_claim, log_access
from veritas.web.views.claims import bp


@bp.post("/caso/<cid>/derivar")
def derive(cid):
    case = load_claim(cid)
    f = request.form
    snap = service.snapshot(case)
    chosen = set(f.getlist("alerta"))
    alerts = [x["title"] for i, x in enumerate(snap["findings"]) if str(i) in chosen]
    alerts += [a.strip() for a in f.get("alertas_extra", "").splitlines() if a.strip()]
    perito = f.get("perito", "").strip()
    empresa = f.get("empresa", "").strip()
    if perito and cx.store.enabled():
        p = cx.store.get(perito)
        if not p or p.get("role") != "perito":
            flash("El perito elegido no existe.", "bad")
            return redirect(url_for("claims.case_view", cid=cid, tab="peritaje"))
        empresa = empresa or p.get("empresa", "")
        if p.get("empresa", "").lower() != empresa.lower():
            flash(f"{p['name']} no pertenece a {empresa}.", "bad")
            return redirect(url_for("claims.case_view", cid=cid, tab="peritaje"))
    try:
        inv = assignment.derive(cx.workdir, case, service.declaration(case) or {}, empresa, perito,
                                f.get("plazo", "").strip(), f.get("instrucciones", "").strip()[:2000],
                                actor_name() or "analista", alerts)
    except ValueError as ex:
        flash(str(ex) or "Revise el plazo (fecha).", "bad")
        return redirect(url_for("claims.case_view", cid=cid, tab="peritaje"))
    log_access("derivar", f"{cid} a {empresa}")
    flash(f"Caso derivado a {empresa}. El perito lo verá en su lista de encargos (expediente {inv.root.name}).", "ok")
    return redirect(url_for("claims.case_view", cid=cid, tab="peritaje"))


@bp.post("/caso/<cid>/derivar/anular")
def derive_cancel(cid):
    case = load_claim(cid)
    reason = request.form.get("motivo", "").strip()[:300]
    if not reason:
        flash("Indique el motivo para anular la derivación.", "bad")
    else:
        try:
            assignment.cancel_derivation(case, actor_name() or "analista", reason)
            flash("Derivación anulada. El expediente del perito se conserva en el historial.", "ok")
        except ValueError as ex:
            flash(str(ex), "bad")
    return redirect(url_for("claims.case_view", cid=cid, tab="peritaje"))


@bp.get("/caso/<cid>/peritaje/informe")
def dossier_report(cid):
    """Informe final que entregó el perito (solo lectura para el analista)."""
    case = load_claim(cid)
    d = assignment.derivation(case)
    path = cx.workdir / d["dossier"] / "informe_final.html" if d else None
    if not path or not path.exists():
        abort(404)
    log_access("descarga", f"informe final de peritaje {cid}")
    return send_file(path, mimetype="text/html")
