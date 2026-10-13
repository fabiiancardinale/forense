"""Administración: usuarios y configuración."""
from __future__ import annotations

import json

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, session, url_for

from evidex.accounts import users as U
from evidex.web.security import start_session
from evidex.core.storage import atomic_json
from evidex.claims import assignment
from evidex.accounts import clients as CL
from evidex.web.common import client_logo_path, current_user, cx, is_admin, load_settings, log_access, user_client

bp = Blueprint("admin", __name__)


def _manageable(username: str) -> bool:
    """El administrador maneja a todos; el jefe, solo a los analistas e investigadores de su empresa."""
    if is_admin():
        return True
    t = cx.store.get(username)
    return bool(t and t["role"] in U.JEFE_CREA and (t.get("cliente") or None) == user_client())


@bp.route("/usuarios", methods=["GET", "POST"])
def users_view():
    first = not cx.store.enabled()
    admin = first or is_admin()
    all_clients = CL.all_clients(cx.workdir)
    if request.method == "POST":
        uname = request.form.get("usuario", "").strip().lower()
        role = request.form.get("rol", "")
        existing = cx.store.get(uname)
        if admin:
            cliente = request.form.get("cliente", "").strip() or None
            if cliente and cliente not in all_clients:
                cliente = None
            if role in ("jefe", "analista", "investigador") and all_clients and not cliente:
                flash("Elija la empresa cliente de este usuario.", "bad")
                return redirect(url_for("admin.users_view"))
        else:                                   # jefe: solo su gente, solo en su empresa
            cliente = user_client()
            if role not in U.JEFE_CREA:
                flash("Usted puede crear analistas e investigadores de su empresa.", "bad")
                return redirect(url_for("admin.users_view"))
            if existing and not _manageable(uname):
                flash("Ese nombre de usuario ya está en uso. Elija otro.", "bad")
                return redirect(url_for("admin.users_view"))
        err = cx.store.add(uname, request.form.get("nombre", ""), role, request.form.get("clave", ""),
                           request.form.get("empresa", ""), cliente=cliente)
        if err:
            flash(err, "bad")
        else:
            if first:
                start_session(cx.store.get(uname))
                cx.store.log(uname, "usuario", f"creó el administrador {uname}", request.remote_addr or "")
                flash("Administrador creado. Desde ahora Evidex pide usuario y contraseña.", "ok")
            else:
                log_access("usuario", f"guardó {uname} ({CL.name_of(cx.workdir, cliente)})")
                flash(f"Usuario {uname} guardado.", "ok")
        return redirect(url_for("admin.users_view"))
    users = cx.store.all()
    if not admin:
        mine = user_client()
        users = {k: v for k, v in users.items() if (v.get("cliente") or None) == mine and v["role"] != "administrador"}
    names = set(users)
    log = [e for e in cx.store.entries() if admin or e.get("user") in names]
    roles = U.ROLES if admin else {k: v for k, v in U.ROLES.items() if k in U.JEFE_CREA}
    return render_template("admin/users.html", users=users, log=_grouped(log), role_choices=roles, is_admin_view=admin, role_names=U.ROLES,
                           role_help=U.ROLE_HELP, actions=U.ACTION_LABELS, firms=assignment.firms(cx.workdir) if admin else [],
                           clients=all_clients, client_name=lambda s: CL.name_of(cx.workdir, s),
                           my_client=CL.name_of(cx.workdir, user_client()) if not admin else "", active="usuarios")


@bp.post("/usuarios/clientes")
def client_add():
    """Empresas cliente (aseguradoras). Solo el administrador."""
    slug, err = CL.add(cx.workdir, request.form.get("nombre", ""))
    flash(err or f"Empresa cliente creada: {request.form.get('nombre', '').strip()}. Ahora cree a su jefe.", "bad" if err else "ok")
    if not err:
        log_access("usuario", f"creó la empresa cliente {slug}")
    return redirect(url_for("admin.users_view"))


@bp.post("/usuarios/empresas")
def firm_add():
    """Empresas de peritaje a las que los analistas pueden derivar casos."""
    err = assignment.save_firm(cx.workdir, request.form.get("nombre", ""), request.form.get("rut", ""),
                               request.form.get("contacto", ""))
    flash(err or "Empresa guardada.", "bad" if err else "ok")
    if not err:
        log_access("usuario", f"guardó la empresa {request.form.get('nombre', '').strip()}")
    return redirect(url_for("admin.users_view") + "#empresas")


def _grouped(entries: list[dict]) -> list[dict]:
    """Junta las filas seguidas iguales (mismo usuario, acción, detalle y equipo, mismo minuto): «Abrió el caso · 7 veces»."""
    out: list[dict] = []
    for e in entries:
        last = out[-1] if out else None
        if last and all(last.get(k) == e.get(k) for k in ("user", "action", "subject", "ip")) and last["ts"][:16] == e["ts"][:16]:
            last["n"] += 1
        else:
            out.append({**e, "n": 1})
    return out


@bp.post("/usuarios/<username>/estado")
def user_toggle(username):
    u = cx.store.get(username)
    if not u or not _manageable(username):
        abort(404)
    err = cx.store.set_active(username, u.get("active", True) is False)
    flash(err or f"Usuario {username} {'activado' if u.get('active', True) is False else 'desactivado'}.", "bad" if err else "ok")
    if not err:
        log_access("usuario", f"{'activó' if u.get('active', True) is False else 'desactivó'} {username}")
    return redirect(url_for("admin.users_view"))


@bp.post("/usuarios/<username>/quitar-2fa")
def user_reset_2fa(username):
    """Si alguien perdió el teléfono: el administrador le quita la verificación en dos pasos (queda registrado)."""
    if not cx.store.get(username) or not _manageable(username):
        abort(404)
    cx.store.set_totp(username, None)
    log_access("2fa_quitada", f"el administrador la quitó a {username}")
    flash(f"Se quitó la verificación en dos pasos de {username}. Al ingresar podrá activarla de nuevo.", "ok")
    return redirect(url_for("admin.users_view"))


@bp.route("/configuracion", methods=["GET", "POST"])
def settings():
    from evidex.forensics import external
    cfg = load_settings()
    if request.method == "POST":
        for k in ("empresa", "direccion_publica", "sightengine_user", "sightengine_secret", "google_vision_key"):
            cfg[k] = request.form.get(k, "").strip()
        cfg["cliente_nombre"] = request.form.get("cliente_nombre", "").strip()[:80]
        err = _guardar_logo(request.files.get("logo_cliente"), request.form.get("logo_autorizado") == "1",
                            request.form.get("quitar_logo") == "1")
        if err:
            flash(err, "bad")
        exigir = request.form.get("exigir_2fa") == "1"
        if exigir != bool(cfg.get("exigir_2fa")):
            log_access("usuario", "exige la verificación en dos pasos" if exigir else "ya no exige la verificación en dos pasos")
        cfg["exigir_2fa"] = exigir
        antes = bool(cfg.get("ia_texto"))
        cfg["ia_texto"] = request.form.get("ia_texto") == "1"
        if antes != cfg["ia_texto"]:
            log_access("ia_texto", "activó el asistente de texto" if cfg["ia_texto"] else "apagó el asistente de texto")
        atomic_json(cx.workdir / "config.json", cfg)
        flash("Configuración guardada.", "ok")
        return redirect(url_for("admin.settings"))
    from evidex.claims import ia_texto
    return render_template("admin/settings.html", cfg=cfg, on=external.configured(cfg), active="config",
                           ia_on=ia_texto.activa(cfg), ia_key=bool(ia_texto.clave()), ia_modelo=ia_texto.modelo())


def _guardar_logo(fs, autorizado: bool, quitar: bool) -> str | None:
    """Logo de la aseguradora: se vuelve a dibujar como PNG (así no entra nada raro escondido en el archivo)."""
    import io
    from PIL import Image
    p = client_logo_path()
    if quitar:
        if p.exists():
            p.unlink()
            log_access("usuario", "quitó el logo del cliente")
        return None
    if not fs or not fs.filename:
        return None
    if not autorizado:
        return "Para usar el logo de la aseguradora, confirme que tiene su autorización escrita."
    data = fs.read(2_000_001)
    if len(data) > 2_000_000:
        return "El logo pesa más de 2 MB."
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ("PNG", "JPEG", "WEBP"):
                return "El logo debe ser PNG, JPG o WEBP (SVG no se acepta por seguridad)."
            im.load()
            im = im.convert("RGBA")
            im.thumbnail((600, 200))
            buf = io.BytesIO()
            im.save(buf, "PNG")
    except Exception:
        return "No se pudo leer el logo: use un PNG, JPG o WEBP."
    from evidex.core.storage import atomic_bytes
    atomic_bytes(p, buf.getvalue())
    log_access("usuario", "cambió el logo del cliente")
    return None


@bp.get("/marca/cliente.png")
def client_logo():
    p = client_logo_path()
    if not p.exists():
        abort(404)
    return send_file(p, mimetype="image/png", max_age=300)
