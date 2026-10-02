"""Administración: usuarios y configuración."""
from __future__ import annotations

import json

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from evidex.accounts import users as U
from evidex.claims import assignment
from evidex.web.common import cx, load_settings, log_access

bp = Blueprint("admin", __name__)


@bp.route("/usuarios", methods=["GET", "POST"])
def users_view():
    first = not cx.store.enabled()
    if request.method == "POST":
        err = cx.store.add(request.form.get("usuario", ""), request.form.get("nombre", ""), request.form.get("rol", ""),
                           request.form.get("clave", ""), request.form.get("empresa", ""))
        if err:
            flash(err, "bad")
        else:
            uname = request.form.get("usuario", "").strip().lower()
            if first:
                session.clear()
                session["user"] = uname
                cx.store.log(uname, "usuario", f"creó el administrador {uname}", request.remote_addr or "")
                flash("Administrador creado. Desde ahora Evidex pide usuario y contraseña.", "ok")
            else:
                log_access("usuario", f"guardó {uname}")
                flash(f"Usuario {uname} guardado.", "ok")
        return redirect(url_for("admin.users_view"))
    return render_template("admin/users.html", users=cx.store.all(), log=cx.store.entries(), roles=U.ROLES,
                           role_help=U.ROLE_HELP, actions=U.ACTION_LABELS, firms=assignment.firms(cx.workdir),
                           active="usuarios")


@bp.post("/usuarios/empresas")
def firm_add():
    """Empresas de peritaje a las que los analistas pueden derivar casos."""
    err = assignment.save_firm(cx.workdir, request.form.get("nombre", ""), request.form.get("rut", ""),
                               request.form.get("contacto", ""))
    flash(err or "Empresa guardada.", "bad" if err else "ok")
    if not err:
        log_access("usuario", f"guardó la empresa {request.form.get('nombre', '').strip()}")
    return redirect(url_for("admin.users_view") + "#empresas")


@bp.post("/usuarios/<username>/estado")
def user_toggle(username):
    u = cx.store.get(username)
    if not u:
        abort(404)
    err = cx.store.set_active(username, u.get("active", True) is False)
    flash(err or f"Usuario {username} {'activado' if u.get('active', True) is False else 'desactivado'}.", "bad" if err else "ok")
    if not err:
        log_access("usuario", f"{'activó' if u.get('active', True) is False else 'desactivó'} {username}")
    return redirect(url_for("admin.users_view"))


@bp.route("/configuracion", methods=["GET", "POST"])
def settings():
    from evidex.forensics import external
    cfg = load_settings()
    if request.method == "POST":
        for k in ("empresa", "direccion_publica", "sightengine_user", "sightengine_secret", "google_vision_key"):
            cfg[k] = request.form.get(k, "").strip()
        (cx.workdir / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        flash("Configuración guardada.", "ok")
        return redirect(url_for("admin.settings"))
    return render_template("admin/settings.html", cfg=cfg, on=external.configured(cfg), active="config")
