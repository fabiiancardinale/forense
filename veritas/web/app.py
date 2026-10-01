"""Fábrica de la aplicación web: configuración, seguridad y registro de las secciones (blueprints)."""
from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, abort, current_app, g, redirect, render_template, request, session, url_for

from veritas.accounts import users as U
from veritas.claims import service
from veritas.core.case import Case
from veritas.web.common import LEVEL_TEXT, cx
from veritas.web.icons import icon
from veritas.web.views import admin, auth, claims, investigations, panel, portal, portfolio, tools

BLUEPRINTS = (panel.bp, claims.bp, portfolio.bp, investigations.bp, portal.bp, tools.bp, auth.bp, admin.bp)
# vistas que no exigen sesión: ingreso y el portal del asegurado (se protege con su enlace secreto)
PUBLIC_ENDPOINTS = {"auth.login", "auth.logout", "static"} | {f"portal.{e}" for e in
                                                              ("capture_page", "capture_upload", "portal_file",
                                                               "portal_story", "portal_finish", "portal_remove")}
NO_NAV = PUBLIC_ENDPOINTS | {"claims.report", "investigations.inv_report"}


def create_app(workdir: Path) -> Flask:
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    app = Flask(__name__)
    key_path = workdir / ".clave_sesion"          # la sesión sobrevive a reiniciar Veritas
    if not key_path.exists():
        key_path.write_bytes(os.urandom(32))
    app.secret_key = key_path.read_bytes()
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", MAX_CONTENT_LENGTH=500 * 1024 * 1024)
    app.config.setdefault("PUBLIC_BASE", "http://127.0.0.1:8765")
    app.extensions["veritas"] = {"workdir": workdir, "registry": workdir / "registro.jsonl", "store": U.Store(workdir)}

    app.jinja_env.globals.update(icon=icon, level_text=LEVEL_TEXT, roles=U.ROLES,
                                 money=lambda n: f"{int(n or 0):,}".replace(",", "."))
    app.jinja_env.filters["extract"] = lambda k, d: d.get(k, k)

    app.before_request(network_guard)
    app.before_request(auth_guard)
    app.context_processor(auth_context)
    app.context_processor(nav_context)
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
    return app


def network_guard():
    """Desde otros equipos (red local o túnel público) solo se puede abrir el portal del asegurado."""
    if request.path.startswith("/c/"):
        return None
    via_tunnel = any(h in request.headers for h in ("Cf-Connecting-Ip", "Cf-Ray", "X-Forwarded-For"))
    host = (request.host or "").rsplit(":", 1)[0].strip("[]").lower()
    if via_tunnel or (current_app.config.get("PUBLIC") and host not in ("127.0.0.1", "localhost", "::1")):
        abort(404)
    if current_app.config.get("LAN") and request.remote_addr not in ("127.0.0.1", "::1"):
        abort(403)
    return None


def _session_user() -> dict | None:
    if not cx.store.enabled():
        return None
    name = session.get("user")
    u = cx.store.get(name) if name else None
    return u if u and u.get("active", True) else None


def auth_guard():
    g.user = None
    # contra envíos desde otras páginas web: si el navegador declara el origen, debe ser este mismo servidor
    if request.method == "POST" and not request.path.startswith("/c/"):
        origin = request.headers.get("Origin")
        if origin and origin.split("://", 1)[-1] != request.host:
            abort(403)
    if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
        return None
    if not cx.store.enabled():
        return None                                   # modo demo: sin usuarios creados
    g.user = _session_user()
    if g.user is None:
        return redirect(url_for("auth.login", next=request.full_path if request.method == "GET" else None))
    if not U.allowed(g.user["role"], request.endpoint):
        return render_template("auth/denied.html", active=""), 403
    return None


def auth_context() -> dict:
    u = getattr(g, "user", None)
    on = cx.store.enabled()
    return {"current_user": u, "auth_on": on, "can": lambda perm: (not on) or (u is not None and U.can(u["role"], perm))}


def nav_context() -> dict:
    """Contador del menú: siniestros de riesgo alto sin decisión."""
    if request.endpoint in NO_NAV or request.method != "GET":
        return {}
    n = 0
    for d in cx.workdir.iterdir():
        if (d / "case.json").exists():
            last = service.last_analysis(Case(d)) or {}
            if last.get("level") == "bad":
                dec = service.current_decision(Case(d))
                n += not dec or dec["subject"] == "en_revision"
    return {"nav_pending": n}
