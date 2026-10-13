"""Asistente de texto con IA (Groq) en el caso: revisar el relato, preguntas para la entrevista, resumen y
transcribir audios. Ver evidex/claims/ia_texto.py."""
from __future__ import annotations

from flask import abort, flash, redirect, url_for

from evidex.claims import ia_texto, service
from evidex.web.common import actor_name, load_claim, load_settings, log_access
from evidex.web.views.claims import bp


def _lista() -> str | None:
    if not ia_texto.clave():
        return "Falta la clave de Groq en el servidor (GROQ_API_KEY en /etc/evidex/evidex.env)."
    if not load_settings().get("ia_texto"):
        return "El asistente de texto está apagado: actívelo en Configuración (requiere autorización de la aseguradora)."
    return None


@bp.post("/caso/<cid>/ia/<tarea>")
def ia_tarea(cid, tarea):
    case = load_claim(cid)
    if tarea not in ia_texto.PROMPTS:
        abort(404)
    if (err := _lista()):
        flash(err, "bad")
    else:
        try:
            ia_texto.ejecutar(case, tarea, actor_name() or "analista")
            log_access("ia_texto", f"{ia_texto.TAREAS[tarea]} · {(service.declaration(case) or {}).get('numero', cid)}")
            flash(f"{ia_texto.TAREAS[tarea]} lista. Es una sugerencia de la IA: revísela con la evidencia.", "ok")
        except ia_texto.IAError as ex:
            flash(str(ex), "bad")
    return redirect(url_for("claims.case_view", cid=cid, tab="peritaje" if tarea == "preguntas" else "resumen") + "#ia")


@bp.post("/caso/<cid>/archivo/<digest>/transcribir")
def ia_transcribir(cid, digest):
    case = load_claim(cid)
    if not service.has_evidence(case, digest) or digest in case.purged():
        abort(404)
    if (err := _lista()):
        flash(err, "bad")
    else:
        try:
            t = ia_texto.transcribir(case, digest, actor_name() or "analista")
            log_access("ia_texto", f"transcribió {t['nombre']}")
            flash(f"Audio «{t['nombre']}» transcrito. Revise el texto: la transcripción puede tener errores.", "ok")
        except ia_texto.IAError as ex:
            flash(str(ex), "bad")
    return redirect(url_for("claims.case_view", cid=cid, tab="documentos") + f"#a-{digest[:12]}")
