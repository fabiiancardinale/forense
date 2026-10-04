"""Interfaz web: registro de casos, validaciones, usuarios y permisos."""
import json
import zipfile


from helpers import ACTUAL, LIMPIO, web_client
from evidex.claims import service


def test_web_create_claim_with_documents_verify_export(demo_src, tmp_path):
    import io as _io
    c = web_client(tmp_path)
    assert "Aún no hay siniestros" in c.get("/").get_data(as_text=True)
    src = demo_src / "actual"
    decl = json.loads((src / "declaracion.json").read_text(encoding="utf-8"))
    form = {k: str(v) for k, v in decl.items() if k not in ("lat", "lon", "fecha_siniestro")}
    form.update({"numero": "SIN-2026-5000", "fecha_siniestro": "2026-09-20T18:30", "lat": "-33,4263", "lon": "-70.6167"})
    files = sorted((src / "fotos").iterdir()) + sorted((src / "documentos").iterdir())
    handles = [(open(p, "rb"), p.name) for p in files]
    r = c.post("/nuevo", data={**form, "fotos": handles}, content_type="multipart/form-data")
    for fh, _ in handles:
        fh.close()
    assert r.status_code == 302 and r.location.endswith("/caso/SIN-2026-5000")
    assert "Derivar a la unidad de investigación" in c.get("/caso/SIN-2026-5000").get_data(as_text=True)
    rep = c.get("/caso/SIN-2026-5000/informe").get_data(as_text=True)
    assert "Documento pasado por un editor de PDF" in rep and "Aumento de cobertura" in rep
    index = c.get("/siniestros").get_data(as_text=True)
    assert "SIN-2026-5000" in index and 'class="risk bad"' in index
    dash = c.get("/").get_data(as_text=True)
    assert "Riesgo alto sin decidir" in dash and "SIN-2026-5000" in dash
    assert "Integridad verificada" in c.post("/caso/SIN-2026-5000/verificar", follow_redirects=True).get_data(as_text=True)
    r = c.get("/caso/SIN-2026-5000/exportar")
    assert r.mimetype == "application/zip" and "verify.py" in zipfile.ZipFile(_io.BytesIO(r.data)).namelist()
    with open(src / "fotos/01_trasera.jpg", "rb") as fh:
        r = c.post("/caso/SIN-2026-5000/fotos", data={"fotos": [(fh, "01_trasera.jpg")]},
                   content_type="multipart/form-data", follow_redirects=True)
    assert "ya estaban en el caso" in r.get_data(as_text=True)


def test_web_validation_and_demo(tmp_path):
    import io as _io
    c = web_client(tmp_path)
    r = c.post("/nuevo", data={"numero": "X1", "fecha_siniestro": "2026-09-20T18:30",
                                "fotos": [(_io.BytesIO(b"hola"), "nota.txt")]}, content_type="multipart/form-data")
    assert r.status_code == 400 and "no son fotos ni PDF" in r.get_data(as_text=True)
    r = c.post("/nuevo", data={"numero": "X1", "fecha_siniestro": "2026-09-20T18:30"}, content_type="multipart/form-data")
    assert "al menos una foto o documento" in r.get_data(as_text=True)
    assert c.get("/caso/..%2Fetc").status_code == 404
    page = c.post("/demo", follow_redirects=True).get_data(as_text=True)
    assert all(n in page for n in ("SIN-2026-0412", "SIN-2026-0533", "SIN-2026-0601", ACTUAL, LIMPIO))
    assert "Derivar a investigación" in page and "Sin alertas" in page
    assert "ya estaba cargado" in c.post("/demo", follow_redirects=True).get_data(as_text=True)


def test_chat_upload_accepted_only_if_real_chat(tmp_path):
    import io as _io
    c = web_client(tmp_path)
    chat = "19/09/26, 21:14 - Ana: hola\n19/09/26, 21:15 - Pedro: chao\n".encode()
    r = c.post("/nuevo", data={"numero": "CH-1", "fecha_siniestro": "2026-09-20T18:30",
                                "fotos": [(_io.BytesIO(chat), "chat_whatsapp.txt")]}, content_type="multipart/form-data")
    assert r.status_code == 302
    r = c.post("/nuevo", data={"numero": "CH-2", "fecha_siniestro": "2026-09-20T18:30",
                                "fotos": [(_io.BytesIO(b"no es un chat"), "notas.txt")]}, content_type="multipart/form-data")
    assert r.status_code == 400 and "chats de WhatsApp" in r.get_data(as_text=True)
    assert "Servicios externos para fotos" in c.get("/configuracion").get_data(as_text=True)
    c.post("/configuracion", data={"empresa": "Consultora X", "google_vision_key": "k"})
    assert "Activos" in c.get("/configuracion").get_data(as_text=True)


def test_users_login_roles_and_access_log(tmp_path):
    from evidex.web import create_app
    app = create_app(tmp_path / "casos", {"DEMO_MODE": True, "CSRF_ENABLED": False, "LEGACY_MODULES": True})
    c = app.test_client()
    assert c.get("/").status_code == 200                                  # sin usuarios: modo demo abierto
    r = c.post("/usuarios", data={"usuario": "ana", "nombre": "Ana Pérez", "rol": "liquidador", "clave": "x" * 12},
               follow_redirects=True)
    assert "primer usuario debe ser administrador" in r.get_data(as_text=True)
    c.post("/usuarios", data={"usuario": "admin", "nombre": "Admin", "rol": "administrador", "clave": "clave-segura-001"})
    c.post("/usuarios", data={"usuario": "ana", "nombre": "Ana Pérez", "rol": "liquidador", "clave": "clave-segura-002"})
    c.post("/usuarios", data={"usuario": "ivan", "nombre": "Iván Inv", "rol": "investigador", "clave": "clave-segura-003"})
    users = json.loads((tmp_path / "casos" / "usuarios.json").read_text(encoding="utf-8"))
    assert "clave-segura-001" not in json.dumps(users) and set(users) == {"admin", "ana", "ivan"}
    c.post("/salir")
    r = c.get("/redes")
    assert r.status_code == 302 and "/ingresar" in r.location                # pide ingresar
    assert c.post("/ingresar", data={"usuario": "ana", "clave": "mala"}).status_code == 401
    r = c.post("/ingresar", data={"usuario": "ana", "clave": "clave-segura-002", "next": "/redes"})
    assert r.status_code == 302 and r.location.endswith("/redes")
    assert c.get("/redes").status_code == 200
    assert c.get("/metricas").status_code == 403 and c.get("/usuarios").status_code == 403   # rol liquidador
    c.post("/demo")
    case = service.find_case(tmp_path / "casos", LIMPIO)
    c.get(f"/caso/{case.root.name}")
    c.post(f"/caso/{case.root.name}/decision", data={"decision": "legitimo", "actor": "otro nombre"})
    assert service.current_decision(case)["actor"] == "Ana Pérez"           # el autor es el usuario, no lo escrito
    assert c.post("/demo", headers={"Origin": "https://sitio-malicioso.example"}).status_code == 403
    c.post("/salir")
    c.post("/ingresar", data={"usuario": "ivan", "clave": "clave-segura-003"})
    assert c.get("/investigaciones").status_code == 200 and c.get(f"/caso/{case.root.name}").status_code == 200
    assert c.post(f"/caso/{case.root.name}/decision", data={"decision": "fraude"}).status_code == 403
    c.post("/salir")
    for _ in range(5):
        c.post("/ingresar", data={"usuario": "admin", "clave": "mala"})
    r = c.post("/ingresar", data={"usuario": "admin", "clave": "clave-segura-001"})
    assert r.status_code == 401 and "Demasiados intentos" in r.get_data(as_text=True)
    log = (tmp_path / "casos" / "accesos.jsonl").read_text(encoding="utf-8")
    assert '"ver_caso"' in log and '"decision"' in log and '"ingreso_fallido"' in log
