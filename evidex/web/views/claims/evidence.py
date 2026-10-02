"""Archivos del caso: agregar, ver, quitar del análisis (sin borrar), restaurar y versiones ocultas de PDF."""
from __future__ import annotations

import io
import re
import tempfile
from pathlib import Path

from flask import abort, flash, redirect, request, send_file, url_for

from evidex.claims import service
from evidex.core.case import sha256_file
from evidex.web.common import actor_name, cx, load_claim, log_access, save_uploads, send_evidence
from evidex.web.views.claims import bp

DIGEST = re.compile(r"[0-9a-f]{64}")


def _back(cid):
    return redirect(url_for("claims.case_view", cid=cid, tab=request.form.get("tab") or request.args.get("tab") or "fotos"))



@bp.post("/caso/<cid>/fotos")
def add_photos(cid):
    case = load_claim(cid)
    with tempfile.TemporaryDirectory() as td:
        photos, rejected = save_uploads(request.files.getlist("fotos"), Path(td))
        added = 0
        for p in photos:
            if not service.has_evidence(case, sha256_file(p)):
                case.add_evidence(p, note=service.evidence_note(p))
                added += 1
    if rejected:
        flash("No se agregaron (no son fotos ni PDF ni chats de WhatsApp): " + ", ".join(rejected), "bad")
    if added:
        service.analyze_claim(case, cx.registry)
        flash(f"{added} archivo(s) agregado(s) y caso reanalizado.", "ok")
    elif photos:
        flash("Esos archivos ya estaban en el caso.", "info")
    return _back(cid)


@bp.post("/caso/<cid>/archivo/<digest>/quitar")
def evidence_exclude(cid, digest):
    case = load_claim(cid)
    motivo = request.form.get("motivo", "").strip()[:200]
    if not service.has_evidence(case, digest) or not motivo:
        flash("Indique el motivo para quitar el archivo.", "bad")
    elif digest not in case.excluded():
        case.exclude_evidence(digest, actor_name() or "analista", motivo)
        log_access("quitar_archivo", digest[:12])
        service.analyze_claim(case, cx.registry)
        flash("Archivo quitado del análisis y caso reanalizado. Sigue guardado en la cadena de custodia.", "ok")
    return _back(cid)


@bp.post("/caso/<cid>/archivo/<digest>/restaurar")
def evidence_restore(cid, digest):
    case = load_claim(cid)
    if digest in case.excluded():
        case.restore_evidence(digest, actor_name() or "analista")
        service.analyze_claim(case, cx.registry)
        flash("Archivo restaurado y caso reanalizado.", "ok")
    return _back(cid)


@bp.get("/caso/<cid>/archivo/<digest>")
def evidence_file(cid, digest):
    """Archivo recibido (foto o documento), para verlo desde el caso. mini=1 entrega una miniatura."""
    return send_evidence(load_claim(cid), digest, bool(request.args.get("mini")))


@bp.get("/caso/<cid>/documento/<digest>/version/<int:n>")
def doc_version(cid, digest, n):
    from evidex.forensics.pdf_versions import version_bytes
    case = load_claim(cid)
    if not DIGEST.fullmatch(digest) or not service.has_evidence(case, digest):
        abort(404)
    name = next((e["data"]["original_name"] for e in case.ledger.entries()
                 if e["action"] == "evidence_added" and e["subject"] == digest), "documento.pdf")
    data = version_bytes((case.evidence_dir / digest).read_bytes(), n)
    log_access("descarga", f"{name} versión {n}")
    if data is None:
        abort(404)
    return send_file(io.BytesIO(data), mimetype="application/pdf", as_attachment=True,
                     download_name=f"{Path(name).stem}_version{n}.pdf")
