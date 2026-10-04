"""Fábrica de la aplicación web: configuración, seguridad y registro de las secciones (blueprints)."""
from __future__ import annotations

import os
import secrets
from datetime import timedelta
from evidex.core.storage import locked, atomic_bytes
from evidex.web.security import (csrf_token, demo_open, portal_count_miss, portal_rate_limit, protect_mutations,
                                 security_headers)
from pathlib import Path

from flask import Flask, abort, current_app, g, redirect, render_template, request, session, url_for

from evidex.accounts import users as U
from evidex.claims import service
from evidex.core.case import Case
from evidex.web.common import LEVEL_TEXT, claim_visible, cx
from evidex.web.icons import icon
from evidex.web.views import admin, auth, claims, investigations, panel, portal, portfolio, tools, inspection

BLUEPRINTS = (inspection.bp, panel.bp, claims.bp, portfolio.bp, investigations.bp, portal.bp, tools.bp, auth.bp, admin.bp)
# vistas que no exigen sesión: ingreso y el portal del asegurado (se protege con su enlace secreto)
PUBLIC_ENDPOINTS = {"auth.login", "auth.logout", "static"} | {f"portal.{e}" for e in
                                                              ("capture_page", "capture_upload", "portal_file",
                                                               "portal_story", "portal_finish", "portal_remove")}
# lo único de /static que se puede abrir desde afuera: el diseño del portal del asegurado
PORTAL_STATIC = {"/static/portal.css"}
NO_NAV = PUBLIC_ENDPOINTS | {"claims.report", "investigations.inv_report"}


def create_app(workdir: Path, config: dict | None = None) -> Flask:
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    app = Flask(__name__)
    key_path = workdir / ".clave_sesion"          # la sesión sobrevive a reiniciar Evidex
    with locked(key_path):
        if not key_path.exists():
            atomic_bytes(key_path, os.urandom(32))
        app.secret_key = key_path.read_bytes()
    app.config.update(DEMO_MODE=False, PRODUCTION=False, LEGACY_MODULES=False, CSRF_ENABLED=True,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
                      SESSION_IDLE_SECONDS=1800, SESSION_ABSOLUTE_SECONDS=28800,
                      MAX_CONTENT_LENGTH=26 * 1024 * 1024, MAX_FORM_PARTS=100,
                      MAX_FORM_MEMORY_SIZE=256 * 1024)
    app.config.update(config or {})
    if app.config['PRODUCTION']:
        if app.config['DEMO_MODE'] or not app.config['CSRF_ENABLED']:
            raise ValueError('Producción requiere autenticación y CSRF.')
        app.config['SESSION_COOKIE_SECURE'] = True
    app.config.setdefault("PUBLIC_BASE", "http://127.0.0.1:8765")
    app.extensions["evidex"] = {"workdir": workdir, "registry": workdir / "registro.jsonl", "store": U.Store(workdir)}

    from evidex.claims.guide import explain
    app.jinja_env.globals.update(explain=explain, icon=icon, level_text=LEVEL_TEXT, roles=U.ROLES,
                                 money=lambda n: f"{int(n or 0):,}".replace(",", "."))
    app.jinja_env.filters["extract"] = lambda k, d: d.get(k, k)

    @app.before_request
    def request_nonce():
        g.csp_nonce = secrets.token_urlsafe(24)

    @app.before_request
    def mvp_scope():
        if not app.config['LEGACY_MODULES'] and request.endpoint and not (
                request.endpoint.startswith(('inspection.', 'auth.', 'admin.')) or request.endpoint in ('static','tools.photo_check','panel.dashboard')):
            abort(404)
        if not app.config['LEGACY_MODULES'] and request.endpoint == 'panel.dashboard':
            return redirect(url_for('inspection.index'))

    app.before_request(network_guard)
    app.before_request(portal_rate_limit)
    app.after_request(portal_count_miss)
    app.before_request(protect_mutations)
    app.after_request(security_headers)

    @app.errorhandler(U.UserStorageError)
    def storage_error(error):
        app.logger.error('User storage unavailable', exc_info=error)
        return 'Registro de usuarios no disponible. Acceso bloqueado; contacte al administrador.', 503

    @app.errorhandler(413)
    def too_large(error):
        return 'Archivo demasiado grande. Máximo 25 MB por carga.', 413

    @app.context_processor
    def security_context():
        return {'csrf_token': csrf_token, 'csp_nonce': g.csp_nonce, 'legacy_modules':app.config['LEGACY_MODULES']}

    app.before_request(auth_guard)
    app.context_processor(auth_context)
    app.context_processor(nav_context)
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
    return app


def network_guard():
    """Desde otros equipos (red local o túnel público) solo se puede abrir el portal del asegurado."""
    if current_app.config['DEMO_MODE'] and request.remote_addr not in ('127.0.0.1', '::1'):
        abort(403)
    if request.path.startswith("/c/") or request.path in PORTAL_STATIC:
        return None
    via_tunnel = any(h in request.headers for h in ("Cf-Connecting-Ip", "Cf-Ray", "X-Forwarded-For"))
    host = (request.host or "").rsplit(":", 1)[0].strip("[]").lower()
    if via_tunnel or (current_app.config.get("PUBLIC") and host not in ("127.0.0.1", "localhost", "::1")):
        abort(404)
    if current_app.config.get("LAN") and request.remote_addr not in ("127.0.0.1", "::1"):
        abort(403)
    return None


def _session_user() -> dict | None:
    name = session.get("user")
    u = cx.store.get(name) if name else None
    if u and u.get('active', True) and cx.store.state.valid(
            session.get('sid'), u, current_app.config['SESSION_IDLE_SECONDS'], current_app.config['SESSION_ABSOLUTE_SECONDS']):
        return u
    session.pop('user', None)
    session.pop('sid', None)
    return None


def auth_guard():
    g.user = None
    if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
        return None
    if demo_open():
        return None
    g.user = _session_user()
    if g.user is None:
        return redirect(url_for("auth.login", next=request.full_path if request.method == "GET" else None))
    if not U.allowed(g.user["role"], request.endpoint):
        return render_template("auth/denied.html", active=""), 403
    return None


def auth_context() -> dict:
    u = getattr(g, "user", None)
    on = not demo_open()
    return {"current_user": u, "auth_on": on, "can": lambda perm: (not on) or (u is not None and U.can(u["role"], perm))}


def nav_context() -> dict:
    """Contador del menú: siniestros de riesgo alto sin decisión."""
    if not current_app.config["LEGACY_MODULES"] or request.endpoint in NO_NAV or request.method != "GET":
        return {}
    n = 0
    for d in cx.workdir.iterdir():
        if not (d / "case.json").exists():
            continue
        case = Case(d)
        if case.kind != "claim" or (service.last_analysis(case) or {}).get("level") != "bad" or not claim_visible(case):
            continue
        dec = service.current_decision(case)
        n += not dec or dec["subject"] == "en_revision"
    return {"nav_pending": n}
