"""Enlace del portal para que el asegurado suba sus fotos y documentos."""
from __future__ import annotations

from flask import flash, redirect, request, url_for

from evidex.web.common import actor_name, load_claim, public_base
from evidex.web.views.claims import bp


@bp.post("/caso/<cid>/captura")
def capture_link(cid):
    from evidex.portal import links
    sent = request.form.get("docs_sent")
    docs = request.form.getlist("docs") if sent else None
    custom = request.form.get("docs_custom", "").split(";") if sent else None
    links.create_link(load_claim(cid), actor=actor_name() or "analista", docs=docs, custom=custom)
    flash("Enlace creado. Envíelo al asegurado con los botones de abajo.", "ok")
    return redirect(url_for("claims.case_view", cid=cid, tab="asegurado"))


@bp.post("/caso/<cid>/captura/enviado")
def capture_sent(cid):
    """Los botones Enviar por WhatsApp, correo o Copiar mensaje avisan aquí con qué dirección salió el enlace."""
    from evidex.portal import links
    case = load_claim(cid)
    data = links.load(case)
    if data and not links.status(data):
        links.mark_sent(case, data, public_base())
    return "", 204
