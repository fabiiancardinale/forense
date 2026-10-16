"""Portal del asegurado (público, por enlace): subida de fotos y documentos."""
from __future__ import annotations


from flask import Blueprint, render_template, request

from evidex.claims import service
from evidex.web.common import cx, load_settings, portal_case, run_claim_analysis

bp = Blueprint("portal", __name__)


@bp.get("/c/<token>")
def capture_page(token):
    from evidex.portal import links as capture
    case, data = capture.find(cx.workdir, token)
    empresa = load_settings().get("empresa", "")
    if not case:
        return render_template("portal/upload.html", error="El enlace no existe o fue reemplazado por uno nuevo.", shots=[],
                               empresa=empresa, numero="", finished=False), 404
    capture.mark_opened(case, data)
    decl = service.declaration(case) or {}
    pr = capture.progress(data, case.excluded())
    sections = [
        {"kind": "photo", "title": "Fotos", "files": pr["photos"], "accept": "image/*,.heic,.heif",
         "lead": "Fotos del vehículo y del daño. Si las tomó el día del choque, súbalas desde la galería de su teléfono: "
                 "así conservamos la fecha y el lugar en que las sacó. Si no tiene, puede tomarlas ahora.",
         "button": "Elegir o tomar fotos", "hint": "Después escriba un título para cada foto"},
        {"kind": "doc", "title": "Documentos", "files": pr["docs"], "accept": "application/pdf,.pdf,image/*,.heic,.docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         "lead": "PDF, Word o foto del documento. Si lo tiene en papel, tómele una foto donde se lea bien; si es un PDF o un "
                 "Word que le enviaron, súbalo tal cual.",
         "button": "Elegir documentos", "hint": "Después escriba un título para cada documento"},
        {"kind": "video", "title": "Videos", "files": pr["videos"], "accept": "video/mp4,video/quicktime,.mp4,.mov,.m4v,.3gp",
         "optional": True,
         "lead": "Si grabó un video del daño o del lugar, súbalo desde la galería de su teléfono (no lo reenvíe por WhatsApp). "
                 "Máximo 3 videos de hasta 300 MB. Se sube por partes: si se corta la señal, sigue sola.",
         "button": "Elegir videos", "hint": "Después escriba un título para cada video"},
    ]
    return render_template("portal/upload.html", error=capture.status(data), finished=bool(data.get("finished")),
                           numero=decl.get("numero", ""), nombre=decl.get("asegurado", ""), empresa=empresa,
                           sections=sections, requested=pr["requested"],
                           story=(data.get("story") or {}).get("text", ""),
                           vence=data["expires"][8:10] + "-" + data["expires"][5:7] + "-" + data["expires"][:4])


@bp.post("/c/<token>/archivo")
def portal_file(token):
    from evidex.portal import links as capture
    case, data = portal_case(token)
    f = request.files.get("archivo")
    if not f or not f.filename:
        return {"error": "No llegó el archivo."}, 400
    try:
        rec = capture.receive_file(case, data, f.filename, f.read(capture.MAX_FILE_BYTES + 1), request.form.get("kind", ""),
                                   request.form.get("titulo", ""), request.headers.get("User-Agent", ""),
                                 request.form.get("modificado", ""))
    except ValueError as ex:
        return {"error": str(ex)}, 400
    return {"ok": True, "tipo": rec["kind"], "titulo": rec["title"], "hora": rec["server_time"][11:16], "id": rec["sha256"]}


@bp.post("/c/<token>/video")
def portal_video(token):
    """Video del asegurado, por partes (ver evidex.web.chunks)."""
    import hashlib
    from evidex.forensics import video
    from evidex.portal import links as capture
    from evidex.web import chunks
    case, data = portal_case(token)
    if why := capture.status(data):
        return {"error": why}, 400
    scope = "portal:" + hashlib.sha256(token.encode()).hexdigest()[:24]
    try:
        r = chunks.receive(cx.workdir, scope, request.form, request.files.get("parte"), video.VIDEO_EXT, video.MAX_BYTES)
    except chunks.ChunkError as ex:
        return {"error": str(ex)}, 400
    if not r["done"]:
        return {"ok": True, "next": r["next"]}
    try:
        rec = capture.receive_video(case, data, r["path"], r["name"], r["meta"]["extra"].get("titulo", ""),
                                    request.headers.get("User-Agent", ""), r["meta"]["extra"].get("modificado", ""))
    except ValueError as ex:
        return {"error": str(ex)}, 400
    finally:
        chunks.finish(r)
    return {"ok": True, "done": True, "tipo": "video", "titulo": rec["title"], "hora": rec["server_time"][11:16],
            "id": rec["sha256"]}


@bp.post("/c/<token>/quitar")
def portal_remove(token):
    from evidex.portal import links as capture
    case, data = portal_case(token)
    try:
        capture.remove_file(case, data, request.form.get("id", ""))
    except ValueError as ex:
        return {"error": str(ex)}, 400
    return {"ok": True}


@bp.post("/c/<token>/relato")
def portal_story(token):
    from evidex.portal import links as capture
    case, data = portal_case(token)
    try:
        capture.save_story(case, data, request.form.get("texto", ""))
    except ValueError as ex:
        return {"error": str(ex)}, 400
    return {"ok": True}


@bp.post("/c/<token>/terminar")
def portal_finish(token):
    from evidex.portal import links as capture
    case, data = portal_case(token)
    try:
        capture.finish(case, data)
    except ValueError as ex:
        return {"error": str(ex)}, 400
    r = run_claim_analysis(case, notify=False)
    if r is None:
        return {"ok": True, "analysis_status": "failed", "warning": "Archivos recibidos; el analista debe reintentar el análisis."}
    return {"ok": True, "analysis_status": "queued" if r.get("background") else "completed"}


@bp.post("/c/<token>/foto")
def capture_upload(token):
    from evidex.portal import links as capture
    case, data = capture.find(cx.workdir, token)
    if not case:
        return {"error": "El enlace no existe."}, 404
    f = request.files.get("foto")
    if not f:
        return {"error": "No llegó la foto."}, 400
    try:
        rec = capture.receive(case, data, f.read(capture.MAX_BYTES + 1), request.form,
                              request.headers.get("User-Agent", ""))
    except ValueError as ex:
        return {"error": str(ex)}, 400
    if len(data["received"]) >= len(data["shots"]):
        if run_claim_analysis(case, notify=False) is None:
            return {"ok": True, "analysis_status": "failed", "hora": rec["server_time"][11:16]}
    return {"ok": True, "hora": rec["server_time"][11:16]}
