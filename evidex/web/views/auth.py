"""Ingreso y salida."""
from __future__ import annotations


import time

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

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
            if u.get("totp"):                       # falta el segundo paso: el código del teléfono
                session.clear()
                session["pending_2fa"] = {"user": u["username"], "ts": time.time(), "next": nxt}
                return redirect(url_for("auth.second_factor"))
            return _enter(u, nxt)
        cx.store.log(request.form.get("usuario", "")[:40], "ingreso_fallido", "", request.remote_addr or "")
        return render_template("auth/login.html", error=err, usuario=request.form.get("usuario"), next=nxt), 401
    return render_template("auth/login.html", error=None, next=nxt)


def _home(u) -> str:
    return url_for("inspection.index" if U.can(u["role"], "ver_siniestros") else "investigations.investigations")


def _enter(u, nxt=""):
    start_session(u)
    cx.store.log(u["username"], "ingreso", "", request.remote_addr or "")
    return redirect(nxt or _home(u))


PENDING_SECONDS = 300


@bp.route("/ingresar/codigo", methods=["GET", "POST"])
def second_factor():
    """Segundo paso: el código de 6 dígitos de la app del teléfono."""
    p = session.get("pending_2fa") or {}
    if not p or time.time() - p.get("ts", 0) > PENDING_SECONDS:
        session.pop("pending_2fa", None)
        return redirect(url_for("auth.login"))
    error = None
    if request.method == "POST":
        u, error = cx.store.check_totp(p["user"], request.form.get("codigo", ""), request.remote_addr or "unknown")
        if u:
            return _enter(u, p.get("next") or "")
        cx.store.log(p["user"][:40], "2fa_fallida", "", request.remote_addr or "")
    return render_template("auth/second_factor.html", error=error), (401 if error else 200)


@bp.route("/mi-cuenta", methods=["GET", "POST"])
def account():
    """Mi cuenta: activar o quitar la verificación en dos pasos."""
    from evidex.accounts import totp
    u = g.get("user")
    if not u:
        return redirect(url_for("auth.login"))
    error = None
    if request.method == "POST":
        action = request.form.get("accion")
        if action == "iniciar":
            session["totp_new"] = totp.new_secret()
        elif action == "confirmar" and session.get("totp_new"):
            if totp.verify(session["totp_new"], request.form.get("codigo", "")) is not None:
                cx.store.set_totp(u["username"], session.pop("totp_new"))
                cx.store.log(u["username"], "2fa_activada", "", request.remote_addr or "")
                start_session(cx.store.get(u["username"]))      # la sesión anterior quedó cerrada al cambiar la cuenta
                flash("Verificación en dos pasos activada. Desde ahora, al ingresar se pedirá el código del teléfono.", "ok")
                return redirect(url_for("auth.account"))
            error = "El código no coincide. Revise que la hora del teléfono esté bien y escriba el código que aparece ahora."
        elif action == "cancelar":
            session.pop("totp_new", None)
        elif action == "quitar" and u.get("totp"):
            if totp.verify(u["totp"], request.form.get("codigo", ""), u.get("totp_step")) is not None:
                cx.store.set_totp(u["username"], None)
                cx.store.log(u["username"], "2fa_quitada", "", request.remote_addr or "")
                start_session(cx.store.get(u["username"]))
                flash("Verificación en dos pasos quitada.", "ok")
                return redirect(url_for("auth.account"))
            error = "Código incorrecto: para quitarla, escriba el código actual de su app."
    secret = session.get("totp_new")
    from evidex.web.common import load_settings
    return render_template("auth/account.html", active="cuenta", error=error, secret=secret,
                           qr=totp.qr_svg(totp.uri(secret, u["username"])) if secret else "",
                           required=bool(load_settings().get("exigir_2fa")), has_2fa=bool(u.get("totp")))


@bp.post("/salir")
def logout():
    if session.get("user"):
        cx.store.log(session["user"], "salida", "", request.remote_addr or "")
    cx.store.state.revoke(session.get("sid"))
    session.clear()
    return redirect(url_for("auth.login"))
