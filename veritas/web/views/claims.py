"""Siniestros: cola de trabajo, registro, ficha del caso, evidencia y decisión."""
from __future__ import annotations

import io
import os
import json
import re
import tempfile
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for

from veritas.claims import service
from veritas.core import export
from veritas.core.case import sha256_file
from veritas.core.ledger import verify_chain, verify_seal
from veritas.portal.links import DEFAULT_DOCS, DOC_TYPES
from veritas.web.common import (FORM_FIELDS, actor_name, claim_list, cx, level_counts, load_claim, load_settings, log_access, public_base, save_uploads, summarize)

bp = Blueprint("claims", __name__)


@bp.get("/siniestros")
def index():
    cases = claim_list()
    return render_template("claims/queue.html", cases=cases, counts=level_counts(cases), workdir=cx.workdir, active="index")


@bp.route("/nuevo", methods=["GET", "POST"])
def new_claim():
    f = request.form
    if request.method == "GET":
        return render_template("claims/new.html", f={}, error=None, active="new", doc_types=DOC_TYPES, default_docs=DEFAULT_DOCS)

    def fail(msg):
        return render_template("claims/new.html", f=f, error=msg, active="new", doc_types=DOC_TYPES, default_docs=DEFAULT_DOCS), 400

    numero = f.get("numero", "").strip()
    fecha = f.get("fecha_siniestro", "").strip()
    if not numero or not fecha:
        return fail("El número de siniestro y la fecha son obligatorios.")
    cid = service.case_id(numero)
    if not cid:
        return fail("El número de siniestro debe contener letras o números.")
    if (cx.workdir / cid / "case.json").exists():
        return fail(f"Ya existe un siniestro con el número {numero}.")
    decl = {k: f.get(k, "").strip() for k in FORM_FIELDS}
    decl["fecha_siniestro"] = fecha if len(fecha) > 16 else fecha + ":00"
    lat, lon = f.get("lat", "").strip(), f.get("lon", "").strip()
    if lat or lon:
        try:
            decl["lat"], decl["lon"] = float(lat.replace(",", ".")), float(lon.replace(",", "."))
        except ValueError:
            return fail("Latitud y longitud deben ser números, por ejemplo -33.4263 y -70.6167.")
    decl = {k: v for k, v in decl.items() if v != ""}

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        photos, rejected = save_uploads(request.files.getlist("fotos"), td)
        if rejected:
            return fail("Estos archivos no son fotos ni PDF ni chats de WhatsApp: " + ", ".join(rejected))
        send_link = f.get("enviar_enlace") == "1"
        if not photos and not send_link:
            return fail("Agregue al menos una foto o documento del siniestro, o marque la opción de enviar el enlace al asegurado.")
        dpath = td / "declaracion.json"
        dpath.write_text(json.dumps(decl, indent=2, ensure_ascii=False), encoding="utf-8")
        case = service.create_claim(cx.workdir, cid, dpath, photos)
    if send_link:
        from veritas.portal import links as capture
        capture.create_link(case, actor=actor_name() or "liquidador", docs=f.getlist("docs"),
                            custom=f.get("docs_custom", "").split(";"))
    r = service.analyze_claim(case, cx.registry)
    if send_link:
        flash("Siniestro registrado. Envíe ahora el enlace al asegurado con los botones de la derecha.", "ok")
    else:
        flash(f"Siniestro creado y analizado: {r['photos']} foto(s), {r['documents']} documento(s), "
              f"{r['findings']} hallazgo(s).", "ok")
    if r.get("reanalyzed"):
        flash("Se reanalizaron los siniestros vinculados: " + ", ".join(r["reanalyzed"]) + ".", "info")
    return redirect(url_for("claims.case_view", cid=cid))


@bp.get("/caso/<cid>")
def case_view(cid):
    case = load_claim(cid)
    # analiza si no hay informe o si llegaron fotos o documentos nuevos desde el último análisis
    n_ev = sum(1 for e in case.ledger.entries()
               if e["action"] in ("evidence_added", "evidence_excluded", "evidence_restored"))
    mark = case.root / "informe.evidencias"
    try:
        seen = int(mark.read_text())
    except (OSError, ValueError):
        seen = -1
    if not (case.root / "informe.html").exists() or seen != n_ev:
        service.analyze_claim(case, cx.registry)
        mark.write_text(str(n_ev))
    from veritas.portal import links as capture
    from veritas.portal import tunnel
    import base64
    cap = capture.load(case)
    cap_url = cap_qr = None
    if cap:
        base = public_base()
        cap_url = f"{base}/c/{cap['token']}"
        png = capture.qr_png(cap_url)
        cap_qr = base64.b64encode(png).decode() if png else None
    summary = summarize(case)
    log_access("ver_caso", summary["numero"])
    excl = case.excluded()
    kinds = {"foto": "Foto", "documento": "Documento", "chat": "Chat de WhatsApp"}
    files = []
    for e in case.ledger.entries():
        if e["action"] != "evidence_added" or e["data"].get("note") == "declaracion":
            continue
        d = e["data"]
        note = d.get("note") or ("documento" if Path(d["original_name"]).suffix.lower() == ".pdf" else "foto")
        files.append({"digest": e["subject"], "title": (d.get("portal") or {}).get("title") or d["original_name"],
                      "kind": kinds.get(note, note.capitalize()),
                      "who": "asegurado" if e["actor"].startswith("asegurado") else e["actor"],
                      "excluded": excl.get(e["subject"])})
    pr = capture.progress(cap, case.excluded()) if cap else None
    share = wa_url = mail_url = None
    cap_state = None
    if cap:
        import urllib.parse as up
        decl = service.declaration(case) or {}
        share = capture.share_message(summary["numero"], decl.get("asegurado", ""), cap_url, cap["expires"],
                                      load_settings().get("empresa", ""))
        if num := capture.wa_number(decl.get("telefono", "")):
            wa_url = f"https://wa.me/{num}?text={up.quote(share)}"
        if decl.get("email"):
            mail_url = (f"mailto:{decl['email']}?subject={up.quote('Siniestro ' + summary['numero'] + ': fotos y documentos')}"
                        f"&body={up.quote(share)}")
        st = capture.status(cap)
        cap_state = "Vencido" if st and not cap.get("finished") else None
    return render_template("claims/case.html", c=summary, active="", decisions=service.DECISIONS,
                           accesos=cx.store.entries(subject=summary["numero"], limit=8) if cx.store.enabled() else [],
                           history=service.decision_history(case), files=files, cap=cap, cap_url=cap_url, cap_qr=cap_qr,
                           cap_lan=current_app.config.get("LAN", False),
                           cap_local=bool(cap_url) and tunnel.is_local(cap_url), pr=pr, share_msg=share, wa_url=wa_url,
                           mail_url=mail_url, cap_state=cap_state, doc_types=DOC_TYPES, default_docs=DEFAULT_DOCS)


@bp.get("/caso/<cid>/informe")
def report(cid):
    case = load_claim(cid)
    return send_file(case.root / "informe.html", mimetype="text/html")


@bp.post("/caso/<cid>/analizar")
def reanalyze(cid):
    r = service.analyze_claim(load_claim(cid), cx.registry)
    flash(f"Análisis actualizado: {r['findings']} hallazgo(s). {r['recommendation']}.", "info")
    if r.get("reanalyzed"):
        flash("También se reanalizaron los siniestros vinculados: " + ", ".join(r["reanalyzed"]) + ".", "info")
    return redirect(url_for("claims.case_view", cid=cid))


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
    return redirect(url_for("claims.case_view", cid=cid))


@bp.post("/caso/<cid>/verificar")
def verify(cid):
    case = load_claim(cid)
    entries = case.ledger.entries()
    chain_ok, chain_msg = verify_chain(entries)
    ev_ok, problems = case.verify_evidence()
    seal_path = case.root / "seal.json"
    seal_ok, seal_msg = (verify_seal(entries, json.loads(seal_path.read_text(encoding="utf-8")),
                                     case.ledger.pub_path.read_bytes())
                         if seal_path.exists() else (False, "sin firma"))
    if chain_ok and ev_ok and seal_ok:
        flash(f"Integridad verificada: {chain_msg}, hashes de evidencia coinciden, firma digital válida.", "ok")
    else:
        detail = [m for ok, m in [(chain_ok, chain_msg), (seal_ok, seal_msg)] if not ok] + problems
        flash("Problema de integridad: " + "; ".join(detail), "bad")
    return redirect(url_for("claims.case_view", cid=cid))


@bp.get("/caso/<cid>/exportar")
def export_zip(cid):
    log_access("descarga", f"paquete verificable {cid}")
    case = load_claim(cid)
    html = (case.root / "informe.html").read_text(encoding="utf-8")
    fd, tmp = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        export.export_bundle(case, html, Path(tmp))
        data = io.BytesIO(Path(tmp).read_bytes())
    finally:
        os.unlink(tmp)
    return send_file(data, mimetype="application/zip", as_attachment=True, download_name=f"{cid}_veritas.zip")


@bp.post("/caso/<cid>/decision")
def decide(cid):
    case = load_claim(cid)
    value, actor = request.form.get("decision", ""), actor_name()
    if value not in service.DECISIONS or not actor:
        flash("Indique la decisión y su nombre.", "bad")
    else:
        service.set_decision(case, value, actor, request.form.get("nota", "").strip())
        log_access("decision", (service.declaration(case) or {}).get("numero", cid))
        flash(f"Decisión registrada: {service.DECISIONS[value]}.", "ok")
    return redirect(url_for("claims.case_view", cid=cid))


@bp.post("/caso/<cid>/captura")
def capture_link(cid):
    from veritas.portal import links as capture
    sent = request.form.get("docs_sent")
    docs = request.form.getlist("docs") if sent else None
    custom = request.form.get("docs_custom", "").split(";") if sent else None
    capture.create_link(load_claim(cid), actor=actor_name() or "liquidador", docs=docs, custom=custom)
    flash("Enlace creado. Envíelo al asegurado con los botones de la derecha.", "ok")
    return redirect(url_for("claims.case_view", cid=cid))


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
    return redirect(url_for("claims.case_view", cid=cid, archivos=1))


@bp.post("/caso/<cid>/archivo/<digest>/restaurar")
def evidence_restore(cid, digest):
    case = load_claim(cid)
    if digest in case.excluded():
        case.restore_evidence(digest, actor_name() or "analista")
        service.analyze_claim(case, cx.registry)
        flash("Archivo restaurado y caso reanalizado.", "ok")
    return redirect(url_for("claims.case_view", cid=cid, archivos=1))


@bp.get("/caso/<cid>/archivo/<digest>")
def evidence_file(cid, digest):
    """Archivo recibido (foto o documento), para verlo desde el caso. mini=1 entrega una miniatura."""
    case = load_claim(cid)
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or not service.has_evidence(case, digest):
        abort(404)
    path = case.evidence_dir / digest
    name = next((e["data"]["original_name"] for e in case.ledger.entries()
                 if e["action"] == "evidence_added" and e["subject"] == digest), "archivo")
    ext = Path(name).suffix.lower()
    if request.args.get("mini") or ext in (".heic", ".heif"):
        try:
            from PIL import Image, ImageOps
            with Image.open(path) as img:
                img = ImageOps.exif_transpose(img).convert("RGB")
                if request.args.get("mini"):
                    img.thumbnail((240, 240))
                buf = io.BytesIO()
                img.save(buf, "JPEG", quality=82)
            return send_file(io.BytesIO(buf.getvalue()), mimetype="image/jpeg", max_age=3600)
        except Exception:
            if request.args.get("mini"):
                abort(404)
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".pdf": "application/pdf",
            ".webp": "image/webp"}.get(ext, "application/octet-stream")
    log_access("ver_archivo", name)
    return send_file(path, mimetype=mime, download_name=name, as_attachment=mime == "application/octet-stream")


@bp.get("/caso/<cid>/documento/<digest>/version/<int:n>")
def doc_version(cid, digest, n):
    from veritas.forensics.pdf_versions import version_bytes
    case = load_claim(cid)
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or not service.has_evidence(case, digest):
        abort(404)
    name = next((e["data"]["original_name"] for e in case.ledger.entries()
                 if e["action"] == "evidence_added" and e["subject"] == digest), "documento.pdf")
    data = version_bytes((case.evidence_dir / digest).read_bytes(), n)
    log_access("descarga", f"{name} versión {n}")
    if data is None:
        abort(404)
    return send_file(io.BytesIO(data), mimetype="application/pdf", as_attachment=True,
                     download_name=f"{Path(name).stem}_version{n}.pdf")


@bp.post("/demo")
def load_demo():
    if not service.DEMO_SCRIPT.exists():
        flash("No se encontró el generador de ejemplo (demo/make_claim_demo.py).", "bad")
        return redirect(url_for("claims.index"))
    done = service.load_demo(cx.workdir)
    if done:
        flash(f"Ejemplo cargado: {len(done)} siniestros ficticios, con fotos y documentos sintéticos. "
              "Abra SIN-2026-0987 para ver la red de siniestros vinculados.", "info")
    else:
        flash("El ejemplo ya estaba cargado.", "info")
    return redirect(url_for("claims.index"))
