"""Ingreso y salida."""
from __future__ import annotations


from flask import Blueprint, redirect, render_template, request, session, url_for

from evidex.accounts import users as U
from evidex.web.common import cx
from evidex.web.security import start_session, demo_open

bp = Blueprint("auth", __name__)


@bp.route("/ingresar", methods=["GET", "POST"])
def login():
    if demo_open():
        return redirect(url_for("panel.dashboard"))
    if not cx.store.all():
        return 'Inicialice el administrador desde la consola: python -m evidex.accounts.setup --dir casos', 503
    nxt = request.values.get("next") or ""
    if not nxt.startswith("/") or nxt.startswith("//") or "\\" in nxt or any(ord(c) < 32 for c in nxt):
        nxt = ""
    if request.method == "POST":
        u, err = cx.store.check(request.form.get("usuario", ""), request.form.get("clave", ""), request.remote_addr or "unknown")
        if u:
            start_session(u)
            cx.store.log(u["username"], "ingreso", "", request.remote_addr or "")
            return redirect(nxt or url_for("inspection.index" if U.can(u["role"], "ver_siniestros") else "investigations.investigations"))
        cx.store.log(request.form.get("usuario", "")[:40], "ingreso_fallido", "", request.remote_addr or "")
        return render_template("auth/login.html", error=err, usuario=request.form.get("usuario"), next=nxt), 401
    return render_template("auth/login.html", error=None, next=nxt)


@bp.post("/salir")
def logout():
    if session.get("user"):
        cx.store.log(session["user"], "salida", "", request.remote_addr or "")
    cx.store.state.revoke(session.get("sid"))
    session.clear()
    return redirect(url_for("auth.login"))
