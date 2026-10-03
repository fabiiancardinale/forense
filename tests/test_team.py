"""Equipo: casos por analista, panel del jefe, reasignación y derivación a peritos externos."""
import io

from helpers import textured_image
from evidex.claims import assignment, service
from evidex.core.case import Case
from evidex.web import create_app

PW = "clave-segura-001"
TRANSCRIPT = ("P: ¿Dónde estaba al momento del choque?\nR: En Av. Grecia con Macul, detenido en el semáforo.\n"
              "P: ¿A qué hora fue?\nR: Cerca de las siete y diez de la tarde.\n")


def _app(tmp_path):
    app = create_app(tmp_path / "casos", {"DEMO_MODE": True, "CSRF_ENABLED": False, "LEGACY_MODULES": True})
    app.config["TESTING"] = True
    store = app.extensions["evidex"]["store"]
    store.add("admin", "Admin", "administrador", PW)
    store.add("jefa", "Jefa Soto", "jefe", PW)
    store.add("ana", "Ana Pérez", "analista", PW)
    store.add("luis", "Luis Mora", "analista", PW)
    work = tmp_path / "casos"
    assignment.save_firm(work, "Peritajes Sur")
    assignment.save_firm(work, "Otra Empresa")
    store.add("perito1", "Pedro Perito", "perito", PW, empresa="Peritajes Sur")
    store.add("perito2", "Paula Otra", "perito", PW, empresa="Otra Empresa")
    return app, work


def _login(c, user):
    c.post("/salir")
    assert c.post("/ingresar", data={"usuario": user, "clave": PW}).status_code == 302


def _new_case(c, numero):
    import zlib
    buf = io.BytesIO()                                                # foto distinta por caso (si no, quedan vinculados)
    textured_image(zlib.crc32(numero.encode()) % 10_000, 480, 360).save(buf, "JPEG", quality=92)
    r = c.post("/nuevo", data={"numero": numero, "fecha_siniestro": "2026-09-30T19:10", "asegurado": f"Persona {numero}",
                               "fotos": (io.BytesIO(buf.getvalue()), "frontal.jpg")}, content_type="multipart/form-data")
    assert r.status_code == 302, r.get_data(as_text=True)[:400]


def test_analyst_sees_only_own_cases_and_boss_reassigns(tmp_path):
    app, work = _app(tmp_path)
    c = app.test_client()
    _login(c, "ana")
    _new_case(c, "SIN-A1")
    _login(c, "luis")
    _new_case(c, "SIN-L1")
    assert assignment.owner(Case(work / "SIN-A1"))["user"] == "ana"
    queue = c.get("/siniestros").get_data(as_text=True)
    assert "SIN-L1" in queue and "SIN-A1" not in queue
    assert c.get("/caso/SIN-A1").status_code == 404                   # caso ajeno: no existe para él
    assert c.get("/caso/SIN-A1/informe").status_code == 404
    assert c.get("/equipo").status_code == 403                        # el panel de equipo es del jefe

    _login(c, "jefa")
    team = c.get("/equipo").get_data(as_text=True)
    assert "Ana Pérez" in team and "Luis Mora" in team and "Carga por analista" in team
    assert "SIN-A1" in c.get("/siniestros").get_data(as_text=True)
    r = c.post("/equipo/reasignar", data={"cid": ["SIN-A1"], "analista": "luis", "motivo": "vacaciones"})
    assert r.status_code == 302
    o = assignment.owner(Case(work / "SIN-A1"))
    assert o["user"] == "luis" and o["by"] == "Jefa Soto" and o["reason"] == "vacaciones"
    _login(c, "luis")
    assert c.get("/caso/SIN-A1").status_code == 200
    hist = c.get("/caso/SIN-A1?tab=historial").get_data(as_text=True)
    assert "Caso asignado" in hist and "vacaciones" in hist
    _login(c, "ana")
    assert c.get("/caso/SIN-A1").status_code == 404


def test_case_tabs_show_everything_in_its_place(tmp_path):
    app, work = _app(tmp_path)
    c = app.test_client()
    _login(c, "ana")
    _new_case(c, "SIN-T1")
    for tab, text in [("", "Alertas principales"), ("fotos", "frontal"), ("documentos", "Aún no hay documentos"),
                      ("peritaje", "Derivar las entrevistas"), ("asegurado", "Crear enlace para el asegurado"),
                      ("informe", "Verificar integridad"), ("historial", "Cadena de custodia")]:
        r = c.get(f"/caso/SIN-T1{'?tab=' + tab if tab else ''}")
        assert r.status_code == 200 and text in r.get_data(as_text=True), tab
    assert c.get("/caso/SIN-T1?tab=otra").status_code == 404


def test_derivation_to_expert_firm_end_to_end(tmp_path):
    app, work = _app(tmp_path)
    c = app.test_client()
    _login(c, "ana")
    _new_case(c, "SIN-D1")
    r = c.post("/caso/SIN-D1/derivar", data={"empresa": "Peritajes Sur", "perito": "perito1", "plazo": "2099-01-31",
                                             "instrucciones": "Entrevistar al conductor", "alertas_extra": "Confirmar la hora"})
    assert r.status_code == 302
    d = assignment.derivation(Case(work / "SIN-D1"))
    assert d["empresa"] == "Peritajes Sur" and d["state"] == "derivado"
    dossier_id = d["dossier"]
    assert "Derivado, sin iniciar" in c.get("/caso/SIN-D1?tab=peritaje").get_data(as_text=True)

    _login(c, "perito2")                                              # perito de otra empresa: no lo ve
    assert dossier_id not in c.get("/investigaciones").get_data(as_text=True)
    assert c.get(f"/investigacion/{dossier_id}").status_code == 404

    _login(c, "perito1")
    assert c.get("/").status_code == 302                              # el perito entra directo a sus encargos
    page = c.get("/investigaciones").get_data(as_text=True)
    assert "Mis encargos" in page and dossier_id in page
    assert c.get("/caso/SIN-D1").status_code == 403                   # no ve el siniestro completo
    assert c.get("/auditar").status_code in (403, 405)
    view = c.get(f"/investigacion/{dossier_id}").get_data(as_text=True)
    assert "Entrevistar al conductor" in view and "Antecedentes del siniestro" in view
    digest = next(e["subject"] for e in Case(work / "SIN-D1").ledger.entries()
                  if e["action"] == "evidence_added" and e["data"].get("note") == "foto")
    assert c.get(f"/investigacion/{dossier_id}/antecedente/{digest}?mini=1").mimetype == "image/jpeg"
    assert c.post(f"/investigacion/{dossier_id}/entregar").status_code == 302      # sin conclusión no se entrega
    assert not assignment.derivation(Case(work / "SIN-D1"))["delivered"]
    c.post(f"/investigacion/{dossier_id}/entrevista", data={"declarante": "Juan Conductor", "rol": "conductor",
                                                             "fecha": "2026-10-02", "texto": TRANSCRIPT})
    assert assignment.derivation(Case(work / "SIN-D1"))["state"] == "en_curso"
    c.post(f"/investigacion/{dossier_id}/conclusion", data={"recomendacion": "Aprobar el pago",
                                                             "texto": "Relato consistente con las fotos."})
    c.post(f"/investigacion/{dossier_id}/entregar")
    d = assignment.derivation(Case(work / "SIN-D1"))
    assert d["state"] == "entregado"
    r = c.post(f"/investigacion/{dossier_id}/entrevista", data={"declarante": "X", "texto": TRANSCRIPT})
    assert len(service.snapshot(Case(work / "SIN-D1"))["photos"]) == 1
    assert (work / dossier_id / "informe_final.html").exists()

    _login(c, "ana")
    tab = c.get("/caso/SIN-D1?tab=peritaje").get_data(as_text=True)
    assert "Informe entregado" in tab and "Juan Conductor" in tab
    assert "Relato consistente" in c.get("/caso/SIN-D1/peritaje/informe").get_data(as_text=True)
    _login(c, "jefa")
    assert "Peritajes Sur" in c.get("/equipo").get_data(as_text=True)


def test_demo_is_shared_among_fictional_team(tmp_path):
    app = create_app(tmp_path / "casos", {"DEMO_MODE": True, "CSRF_ENABLED": False, "LEGACY_MODULES": True})
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/demo")
    work = tmp_path / "casos"
    owners = {assignment.owner(x)["user"] for x in service.claim_cases(work)}
    assert owners == {"camila.rojas", "diego.munoz"}
    states = {assignment.derivation(x)["state"] for x in service.claim_cases(work) if assignment.derivation(x)}
    assert states == {"derivado", "atrasado"}
    team = c.get("/equipo").get_data(as_text=True)
    assert "Camila Rojas" in team and "Investigaciones Andes" in team and "atrasado" in team
