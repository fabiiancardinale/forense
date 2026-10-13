"""Logo del cliente: solo con autorización, solo imágenes (se vuelven a dibujar como PNG), visible en el ingreso."""
import io

from PIL import Image


def _client(tmp_path):
    from evidex.web import create_app
    app = create_app(tmp_path / "casos", {"DEMO_MODE": True, "CSRF_ENABLED": False, "LEGACY_MODULES": True})
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/usuarios", data={"usuario": "admin", "nombre": "Admin", "rol": "administrador", "clave": "clave-segura-001"})
    c.post("/usuarios", data={"usuario": "ana", "nombre": "Ana", "rol": "analista", "clave": "clave-segura-002"})
    return c


def _png():
    b = io.BytesIO()
    Image.new("RGB", (900, 300), "#335").save(b, "PNG")
    b.seek(0)
    return b


def test_logo_del_cliente(tmp_path):
    c = _client(tmp_path)
    c.post("/salir")
    c.post("/ingresar", data={"usuario": "admin", "clave": "clave-segura-001"})
    logo = tmp_path / "casos" / "marca" / "cliente.png"
    # sin confirmar la autorización: no se guarda
    r = c.post("/configuracion", data={"cliente_nombre": "Aseguradora X", "logo_cliente": (_png(), "l.png")},
               content_type="multipart/form-data", follow_redirects=True)
    assert "autorización escrita" in r.get_data(as_text=True) and not logo.exists()
    # un SVG o algo que no es imagen: no
    r = c.post("/configuracion", data={"logo_cliente": (io.BytesIO(b"<svg onload=alert(1)></svg>"), "l.svg"),
                                       "logo_autorizado": "1"}, content_type="multipart/form-data", follow_redirects=True)
    assert not logo.exists()
    c.post("/configuracion", data={"cliente_nombre": "Aseguradora X", "logo_cliente": (_png(), "l.png"),
                                   "logo_autorizado": "1"}, content_type="multipart/form-data")
    assert logo.exists() and Image.open(logo).size == (600, 200)
    assert "Aseguradora X" in c.get("/siniestros").get_data(as_text=True)
    # el ingreso lo muestra sin sesión
    c.post("/salir")
    assert "/marca/cliente.png" in c.get("/ingresar").get_data(as_text=True)
    assert c.get("/marca/cliente.png").mimetype == "image/png"
    # un analista no puede cambiarlo
    c.post("/ingresar", data={"usuario": "ana", "clave": "clave-segura-002"})
    assert c.post("/configuracion", data={"quitar_logo": "1"}).status_code == 403
    c.post("/salir")
    c.post("/ingresar", data={"usuario": "admin", "clave": "clave-segura-001"})
    c.post("/configuracion", data={"quitar_logo": "1"})
    assert not logo.exists() and c.get("/marca/cliente.png").status_code == 404
