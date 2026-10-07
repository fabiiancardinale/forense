"""Archivos del caso: agregar, ver, quitar del análisis (sin borrar), restaurar y versiones ocultas de PDF."""
from __future__ import annotations

import io
import re
import tempfile
from pathlib import Path

from flask import abort, flash, redirect, request, send_file, url_for

from evidex.claims import service
from evidex.core.case import sha256_file
from evidex.web.common import actor_name, load_claim, log_access, run_claim_analysis, save_uploads, send_evidence
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
            d = sha256_file(p)
            if not service.has_evidence(case, d) or d in case.purged():       # eliminado antes: vuelve a entrar
                case.add_evidence(p, note=service.evidence_note(p))
                added += 1
    if rejected:
        flash("No se agregaron: " + ", ".join(rejected), "bad")
    if added:
        r = run_claim_analysis(case)
        flash(f"{added} archivo(s) agregado(s)" + ("; analizando el caso." if r and r.get("background") else
                                                   " y caso reanalizado."), "ok")
    elif photos:
        flash("Esos archivos ya estaban en el caso.", "info")
    return _back(cid)


@bp.post("/caso/<cid>/archivo/<digest>/quitar")
def evidence_exclude(cid, digest):
    case = load_claim(cid)
    motivo = request.form.get("motivo", "").strip()[:200]
    if not service.has_evidence(case, digest) or digest in case.purged() or not motivo:
        flash("Indique el motivo para quitar el archivo.", "bad")
    elif digest not in case.excluded():
        case.exclude_evidence(digest, actor_name() or "analista", motivo)
        log_access("quitar_archivo", digest[:12])
        r = run_claim_analysis(case)
        flash("Archivo quitado del análisis" + ("; analizando el caso." if r and r.get("background") else
                                                " y caso reanalizado.") + " Sigue guardado en la cadena de custodia.", "ok")
    return _back(cid)


@bp.post("/caso/<cid>/archivo/<digest>/restaurar")
def evidence_restore(cid, digest):
    case = load_claim(cid)
    if digest in case.purged():
        flash("Ese archivo se eliminó definitivamente: no se puede restaurar.", "bad")
    elif digest in case.excluded():
        case.restore_evidence(digest, actor_name() or "analista")
        r = run_claim_analysis(case)
        flash("Archivo restaurado" + ("; analizando el caso." if r and r.get("background") else " y caso reanalizado."), "ok")
    return _back(cid)


PURGE_REASONS = ("Datos de prueba", "Pedido de borrado del asegurado (Ley 21.719)",
                 "Plazo de conservación cumplido", "Contiene datos de terceros agregados por error")


@bp.post("/caso/<cid>/archivo/<digest>/eliminar")
def evidence_purge(cid, digest):
    """Eliminación definitiva de un archivo ya quitado del análisis. Queda la constancia en la cadena."""
    from evidex.claims import analysis
    from evidex.web.common import cx
    case = load_claim(cid)
    motivo = request.form.get("motivo", "").strip()
    if not DIGEST.fullmatch(digest or "") or not service.has_evidence(case, digest) or digest in case.purged():
        abort(404)
    if motivo not in PURGE_REASONS or request.form.get("confirmar", "").strip().upper() != "ELIMINAR":
        flash("Para eliminar definitivamente, elija el motivo y escriba ELIMINAR.", "bad")
        return _back(cid)
    try:
        name = case.purge_evidence(digest, actor_name() or "administrador", motivo)
    except (KeyError, ValueError) as ex:
        flash(str(ex).strip("'\""), "bad")
        return _back(cid)
    numero = (service.declaration(case) or {}).get("numero")
    if numero:
        analysis.purge_from_registry(cx.registry, numero, digest)
    log_access("eliminar_archivo", f"{name} ({digest[:12]})")
    r = run_claim_analysis(case)
    flash(f"«{name}» eliminado definitivamente. Queda la constancia en el historial del caso"
          + ("; analizando el caso." if r and r.get("background") else "."), "ok")
    return _back(cid)


@bp.get("/caso/<cid>/archivo/<digest>")
def evidence_file(cid, digest):
    """Archivo recibido (foto o documento), para verlo desde el caso. mini=1 entrega una miniatura."""
    return send_evidence(load_claim(cid), digest, bool(request.args.get("mini")))


@bp.get("/caso/<cid>/archivo/<digest>/metadatos")
def evidence_metadata(cid, digest):
    """Todo lo que trae el archivo: estructura, EXIF, nota del fabricante, XMP, IPTC, ICC, Samsung, Google, Apple, C2PA."""
    from flask import render_template
    from evidex.forensics.deep_meta import read_all
    case = load_claim(cid)
    if not re.fullmatch(r"[0-9a-f]{64}", digest or "") or not service.has_evidence(case, digest) or digest in case.purged():
        abort(404)
    name = next((e["data"].get("original_name") for e in case.ledger.entries()
                 if e["action"] == "evidence_added" and e["subject"] == digest), digest[:12])
    log_access("ver_metadatos", name)
    data = read_all(case.evidence_dir / digest)
    data["archivo"]["Nombre"] = name
    return render_template("claims/metadata.html", data=data, name=name, cid=cid, digest=digest, sections=META_SECTIONS,
                           active="index")


def _content(case, digest: str) -> dict:
    """Análisis de píxeles guardado de una foto del caso (zonas pegadas, grano, clonado, modelo de IA)."""
    import json
    try:
        cache = json.loads((case.root / "analisis_imagen.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    c = cache.get(digest) if isinstance(cache, dict) else None
    return c if isinstance(c, dict) else {}


def _ai_confirmed(case, digest: str) -> bool:
    """¿Otra prueba ya confirmó que esta foto se editó con IA (firma del teléfono, marca visible, copia)?"""
    from evidex.forensics.image_content import AI_CONFIRMED
    snap = service.snapshot(case) or {}
    return any(f.get("rule") in AI_CONFIRMED and any(str(e).startswith(digest[:8]) for e in f.get("evidence") or [])
               for f in snap.get("findings") or [])


def _evidence_name(case, digest: str) -> str:
    return next((e["data"].get("original_name") for e in case.ledger.entries()
                 if e["action"] == "evidence_added" and e["subject"] == digest), digest[:12])


@bp.get("/caso/<cid>/archivo/<digest>/zonas")
def evidence_zones(cid, digest):
    """La foto con las zonas sospechosas marcadas en colores, con su leyenda y las alertas de esa foto."""
    from flask import render_template
    from evidex.claims.guide import explain
    from evidex.forensics.image_content import ZONE_LEGEND, zones
    case = load_claim(cid)
    if not DIGEST.fullmatch(digest or "") or not service.has_evidence(case, digest) or digest in case.purged():
        abort(404)
    name = _evidence_name(case, digest)
    found = zones(_content(case, digest), confirmed=_ai_confirmed(case, digest))
    log_access("ver_zonas", name)
    legend = [(c, t, why) for c, t, why in ZONE_LEGEND if t in found]
    return render_template("claims/zones.html", cid=cid, digest=digest, name=name, legend=legend, active="index")


@bp.get("/caso/<cid>/archivo/<digest>/zonas.png")
def evidence_zones_image(cid, digest):
    from evidex.forensics.image_content import overlay
    case = load_claim(cid)
    if not DIGEST.fullmatch(digest or "") or not service.has_evidence(case, digest) or digest in case.purged():
        abort(404)
    try:
        png = overlay(case.evidence_dir / digest, _content(case, digest), maxside=1400, upright=True,
                      confirmed=_ai_confirmed(case, digest))
    except Exception:
        png = None
    if not png:
        abort(404)
    return send_file(io.BytesIO(png), mimetype="image/png", max_age=0)


META_SECTIONS = [("archivo", "Archivo"), ("samsung", "Samsung: datos propios del teléfono (SEF)"),
                 ("apple", "Apple"), ("google", "Google / Android (XMP de cámara)"), ("c2pa", "Credenciales de contenido (C2PA)"),
                 ("exif", "EXIF (todas las carpetas)"), ("fabricante", "Nota del fabricante (MakerNote)"), ("xmp", "XMP"),
                 ("iptc", "IPTC / Photoshop"), ("icc", "Perfil de color (ICC)"), ("jpeg", "Compresión JPEG"),
                 ("png", "Bloques de texto PNG"), ("dates", "Todas las fechas encontradas")]


@bp.get("/caso/<cid>/documento/<digest>/version/<int:n>")
def doc_version(cid, digest, n):
    from evidex.forensics.pdf_versions import version_bytes
    case = load_claim(cid)
    if not DIGEST.fullmatch(digest) or not service.has_evidence(case, digest) or digest in case.purged():
        abort(404)
    name = next((e["data"]["original_name"] for e in case.ledger.entries()
                 if e["action"] == "evidence_added" and e["subject"] == digest), "documento.pdf")
    data = version_bytes((case.evidence_dir / digest).read_bytes(), n)
    log_access("descarga", f"{name} versión {n}")
    if data is None:
        abort(404)
    return send_file(io.BytesIO(data), mimetype="application/pdf", as_attachment=True,
                     download_name=f"{Path(name).stem}_version{n}.pdf")
