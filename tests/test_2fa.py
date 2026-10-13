"""Verificación en dos pasos: códigos TOTP (RFC 6238), activación, ingreso con código, exigencia y reseteo."""
import re

from evidex.accounts import totp


def test_totp_rfc6238():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"           # «12345678901234567890» del RFC
    assert totp.code_at(secret, 59 // 30) == "287082"
    assert totp.code_at(secret, 1111111109 // 30) == "081804"
    assert totp.verify(secret, "287082", t=59) == 1
    assert totp.verify(secret, "287082", last_step=1, t=59) is None     # no se acepta dos veces
    assert totp.verify(secret, "000000", t=59) is None
    assert totp.uri(secret, "ana").startswith("otpauth://totp/Evidex:ana?secret=")
    assert "<svg" in totp.qr_svg(totp.uri(secret, "ana"))


def _app(tmp_path):
    from evidex.web import create_app
    app = create_app(tmp_path / "casos", {"CSRF_ENABLED": False, "LEGACY_MODULES": True})
    app.config["TESTING"] = True
    store = app.extensions["evidex"]["store"]
    store.add("admin", "Admin", "administrador", "clave-segura-001")
    store.add("ana", "Ana", "analista", "clave-segura-002")
    return app, store


def _code(secret):
    return totp.code_at(secret, totp.now_step())


def test_activar_e_ingresar_con_codigo(tmp_path):
    app, store = _app(tmp_path)
    c = app.test_client()
    c.post("/ingresar", data={"usuario": "ana", "clave": "clave-segura-002"})
    c.post("/mi-cuenta", data={"accion": "iniciar"})
    page = c.get("/mi-cuenta").get_data(as_text=True)
    secret = re.search(r'class="mono secret">([A-Z2-7]+)<', page).group(1)
    assert "<svg" in page
    r = c.post("/mi-cuenta", data={"accion": "confirmar", "codigo": "000000"})
    assert "no coincide" in r.get_data(as_text=True) and not store.get("ana").get("totp")
    r = c.post("/mi-cuenta", data={"accion": "confirmar", "codigo": _code(secret)}, follow_redirects=True)
    assert "activada" in r.get_data(as_text=True) and store.get("ana")["totp"] == secret
    assert c.get("/siniestros").status_code == 200                       # sigue dentro (sesión renovada)
    c.post("/salir")
    # ingreso: la contraseña sola ya no basta
    r = c.post("/ingresar", data={"usuario": "ana", "clave": "clave-segura-002"})
    assert r.status_code == 302 and r.location.endswith("/ingresar/codigo")
    assert c.get("/siniestros").status_code == 302                       # todavía sin sesión
    r = c.post("/ingresar/codigo", data={"codigo": "123456"})
    assert r.status_code == 401 and "Código incorrecto" in r.get_data(as_text=True)
    store._save_step("ana", 0)                                             # el código anterior no cuenta
    r = c.post("/ingresar/codigo", data={"codigo": _code(secret)})
    assert r.status_code == 302 and c.get("/siniestros").status_code == 200
    # el mismo código no sirve dos veces
    c.post("/salir")
    c.post("/ingresar", data={"usuario": "ana", "clave": "clave-segura-002"})
    assert c.post("/ingresar/codigo", data={"codigo": _code(secret)}).status_code == 401


def test_exigir_y_resetear(tmp_path):
    app, store = _app(tmp_path)
    c = app.test_client()
    c.post("/ingresar", data={"usuario": "admin", "clave": "clave-segura-001"})
    c.post("/configuracion", data={"exigir_2fa": "1"})
    # sin 2FA, cualquier página lleva a «Mi cuenta»
    r = c.get("/siniestros")
    assert r.status_code == 302 and r.location.endswith("/mi-cuenta")
    assert "exige la verificación en dos pasos" in c.get("/mi-cuenta").get_data(as_text=True)
    store.set_totp("ana", totp.new_secret())
    # el administrador se la quita a quien perdió el teléfono (desde Usuarios)
    store.set_totp("admin", totp.new_secret())
    with c.session_transaction() as s:
        s.clear()
    secret = store.get("admin")["totp"]
    c.post("/ingresar", data={"usuario": "admin", "clave": "clave-segura-001"})
    c.post("/ingresar/codigo", data={"codigo": _code(secret)})
    assert "2 pasos" in c.get("/usuarios").get_data(as_text=True)
    c.post("/usuarios/ana/quitar-2fa")
    assert not store.get("ana").get("totp")
    # un analista no puede quitársela a otro
    a = app.test_client()
    a.post("/ingresar", data={"usuario": "ana", "clave": "clave-segura-002"})
    assert a.post("/usuarios/admin/quitar-2fa").status_code in (302, 403)
    assert store.get("admin").get("totp")
