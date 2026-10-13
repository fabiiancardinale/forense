"""Evidex en un servidor (VPS) detrás de Caddy: HTTPS, IP real del visitante, todo Evidex con usuario y contraseña,
el portal del asegurado abierto y, si se configura, solo desde las redes de la compañía."""
import re

from evidex.web.wsgi import build, redes

HOST = "evidex.ejemplo.cl"
FWD = {"X-Forwarded-For": "200.10.20.30", "X-Forwarded-Proto": "https", "X-Forwarded-Host": HOST}


def _app(tmp_path, **env):
    app = build({"EVIDEX_DIR": str(tmp_path / "casos"), **env})
    app.config["TESTING"] = True
    from evidex.web.common import cx  # noqa: F401
    with app.app_context():
        assert app.extensions["evidex"]["store"].add("admin", "Admin", "administrador", "clave-segura-servidor-01") is None
    return app


def _login(c):
    page = c.get("/ingresar", headers=FWD, base_url=f"https://{HOST}")
    assert page.status_code == 200
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True)).group(1)
    return c.post("/ingresar", data={"usuario": "admin", "clave": "clave-segura-servidor-01", "csrf_token": token},
                  headers={**FWD, "Origin": f"https://{HOST}"}, base_url=f"https://{HOST}")


def test_server_mode_behind_proxy(tmp_path):
    app = _app(tmp_path)
    assert app.config["PRODUCTION"] and app.config["SERVER"] and app.config["LEGACY_MODULES"]
    c = app.test_client()
    r = _login(c)
    assert r.status_code == 302, r.get_data(as_text=True)[:300]
    # todo Evidex se abre desde internet (con sesión), con HTTPS estricto y cookie segura
    r = c.get("/siniestros", headers=FWD, base_url=f"https://{HOST}")
    assert r.status_code == 200
    assert "max-age" in r.headers.get("Strict-Transport-Security", "")
    assert app.config["SESSION_COOKIE_SECURE"]
    # la IP que queda en el registro de accesos es la del visitante, no la de Caddy
    log = (tmp_path / "casos" / "accesos.jsonl").read_text()
    assert "200.10.20.30" in log
    # sin sesión: al ingreso
    assert c.__class__(app).get("/siniestros", headers=FWD, base_url=f"https://{HOST}").status_code == 302


def test_allowed_networks(tmp_path):
    app = _app(tmp_path, EVIDEX_IPS_PERMITIDAS="10.0.0.0/8, 190.5.6.7")
    c = app.test_client()
    assert c.get("/ingresar", headers=FWD, base_url=f"https://{HOST}").status_code == 403
    assert c.get("/ingresar", headers={**FWD, "X-Forwarded-For": "190.5.6.7"}, base_url=f"https://{HOST}").status_code == 200
    assert c.get("/ingresar", headers={**FWD, "X-Forwarded-For": "10.1.2.3"}, base_url=f"https://{HOST}").status_code == 200
    # el portal del asegurado sigue abierto desde cualquier lugar (un enlace que no existe da 404, no 403)
    assert c.get("/c/no-existe", headers=FWD, base_url=f"https://{HOST}").status_code == 404
    assert c.get("/static/portal.css", headers=FWD, base_url=f"https://{HOST}").status_code == 200


def test_networks_parsing():
    assert [str(n) for n in redes(" 10.0.0.0/8; 190.5.6.7 ,")] == ["10.0.0.0/8", "190.5.6.7/32"]
    assert redes("") == []
