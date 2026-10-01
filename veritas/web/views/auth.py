"""Ingreso y salida."""
from __future__ import annotations


from flask import Blueprint, redirect, render_template, request, session, url_for

from veritas.accounts import users as U
from veritas.web.common import cx

bp = Blueprint("auth", __name__)


@bp.route("/ingresar", methods=["GET", "POST"])
def login():
    if not cx.store.enabled():
        return redirect(url_for("panel.dashboard"))
    nxt = request.values.get("next") or ""
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = ""
    if request.method == "POST":
        u, err = cx.store.check(request.form.get("usuario", ""), request.form.get("clave", ""))
        if u:
            session.clear()
            session["user"] = u["username"]
            cx.store.log(u["username"], "ingreso", "", request.remote_addr or "")
            return redirect(nxt or url_for("panel.dashboard" if U.can(u["role"], "ver_siniestros") else "investigations.investigations"))
        cx.store.log(request.form.get("usuario", "")[:40], "ingreso_fallido", "", request.remote_addr or "")
        return render_template("auth/login.html", error=err, usuario=request.form.get("usuario"), next=nxt), 401
    return render_template("auth/login.html", error=None, next=nxt)


@bp.get("/salir")
def logout():
    if session.get("user"):
        cx.store.log(session["user"], "salida", "", request.remote_addr or "")
    session.clear()
    return redirect(url_for("auth.login"))
