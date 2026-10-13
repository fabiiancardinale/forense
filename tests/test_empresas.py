"""Empresas cliente: cada aseguradora ve solo lo suyo; el jefe crea a su gente; el analista ve lo asignado."""
import io

from helpers import textured_image
from evidex.accounts import clients
from evidex.claims import assignment, service

PW = "clave-segura-0001"


def _app(tmp_path):
    from evidex.web import create_app
    app = create_app(tmp_path / "casos", {"CSRF_ENABLED": False, "LEGACY_MODULES": True})
    app.config["TESTING"] = True
    store = app.extensions["evidex"]["store"]
    store.add("fabian", "Fabián", "administrador", PW)
    wd = tmp_path / "casos"
    clients.add(wd, "BCI Seguros")
    clients.add(wd, "Otra Aseguradora")
    store.add("jefe.bci", "Jefe BCI", "jefe", PW, cliente="bci-seguros")
    store.add("jefe.otra", "Jefe Otra", "jefe", PW, cliente="otra-aseguradora")
    return app, store, wd


def _login(app, user):
    c = app.test_client()
    c.post("/ingresar", data={"usuario": user, "clave": PW})
    return c


def _nuevo(c, numero, **extra):
    b = io.BytesIO()
    textured_image(7, 640, 480).save(b, "JPEG")
    b.seek(0)
    return c.post("/nuevo", data={"numero": numero, "fecha_siniestro": "2026-10-01T10:00", "asegurado": "Ana",
                                  "fotos": [(b, "f.jpg")], **extra}, content_type="multipart/form-data")


def test_cada_empresa_ve_solo_lo_suyo(tmp_path):
    app, store, wd = _app(tmp_path)
    jb, jo = _login(app, "jefe.bci"), _login(app, "jefe.otra")
    assert _nuevo(jb, "SIN-B1").status_code == 302 and _nuevo(jo, "SIN-O1").status_code == 302
    assert clients.of_case(service.find_case(wd, "SIN-B1")) == "bci-seguros"
    cola = jb.get("/siniestros").get_data(as_text=True)
    assert "SIN-B1" in cola and "SIN-O1" not in cola
    assert jb.get("/caso/SIN-O1").status_code == 404                 # ni por dirección directa
    assert jb.get("/caso/SIN-O1/vista").status_code == 404
    assert jo.get("/caso/SIN-B1?tab=fotos").status_code == 404
    # el administrador ve todo y puede mover un caso de empresa
    adm = _login(app, "fabian")
    cola = adm.get("/siniestros").get_data(as_text=True)
    assert "SIN-B1" in cola and "SIN-O1" in cola
    # redes y registro: uno por empresa
    assert (wd / "registros" / "bci-seguros.jsonl").exists() and (wd / "registros" / "otra-aseguradora.jsonl").exists()
    assert "SIN-O1" not in (wd / "registros" / "bci-seguros.jsonl").read_text(encoding="utf-8")


def test_jefe_crea_su_equipo_y_analista_ve_lo_asignado(tmp_path):
    app, store, wd = _app(tmp_path)
    jb = _login(app, "jefe.bci")
    # el jefe crea un analista: queda en su empresa aunque intente otra
    jb.post("/usuarios", data={"usuario": "ana", "nombre": "Ana", "rol": "analista", "clave": PW, "cliente": "otra-aseguradora"})
    assert store.get("ana")["cliente"] == "bci-seguros"
    # no puede crear jefes ni administradores, ni tomar el usuario de otra empresa
    jb.post("/usuarios", data={"usuario": "x", "nombre": "X", "rol": "administrador", "clave": PW})
    assert store.get("x") is None
    jb.post("/usuarios", data={"usuario": "jefe.otra", "nombre": "Robado", "rol": "analista", "clave": PW})
    assert store.get("jefe.otra")["role"] == "jefe" and store.get("jefe.otra")["cliente"] == "otra-aseguradora"
    # solo ve a su gente
    page = jb.get("/usuarios").get_data(as_text=True)
    assert "ana" in page and "jefe.otra" not in page and "fabian" not in page and "Empresas de peritaje" not in page
    assert jb.post("/usuarios/jefe.otra/estado").status_code == 404
    assert jb.get("/configuracion").status_code == 403
    # el analista ve solo lo asignado
    _nuevo(jb, "SIN-B1")
    _nuevo(jb, "SIN-B2", analista="ana")
    ana = _login(app, "ana")
    cola = ana.get("/siniestros").get_data(as_text=True)
    assert "SIN-B2" in cola and "SIN-B1" not in cola
    assert ana.get("/caso/SIN-B1").status_code == 404
    assert ana.get("/usuarios").status_code == 403
    # reasignar: el jefe no puede tocar casos de otra empresa
    jo = _login(app, "jefe.otra")
    _nuevo(jo, "SIN-O1")
    jb.post("/equipo/reasignar", data={"cid": "SIN-O1", "analista": "ana"})
    assert (assignment.owner(service.find_case(wd, "SIN-O1")) or {}).get("user") != "ana"


def test_casos_sin_empresa_solo_admin(tmp_path):
    app, store, wd = _app(tmp_path)
    adm = _login(app, "fabian")
    _nuevo(adm, "SIN-VIEJO", cliente="")
    case = service.find_case(wd, "SIN-VIEJO")
    assert clients.of_case(case) is None
    jb = _login(app, "jefe.bci")
    assert jb.get("/caso/SIN-VIEJO").status_code == 404
    adm.post("/caso/SIN-VIEJO/empresa", data={"cliente": "bci-seguros"})
    assert clients.of_case(case) == "bci-seguros" and jb.get("/caso/SIN-VIEJO").status_code == 200
    assert any(e["action"] == "cliente_asignado" for e in case.ledger.entries())
    assert jb.post("/caso/SIN-VIEJO/empresa", data={"cliente": ""}).status_code == 403
