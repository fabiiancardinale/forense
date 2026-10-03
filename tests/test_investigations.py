"""Expedientes de peritos, entrevistas y auditoría de informes."""
import zipfile


from helpers import INV_DEMO, web_client
from evidex.core.case import Case
from evidex.core.ledger import verify_chain
from evidex.investigations import audit as RA
from evidex.investigations import dossier as INV
from evidex.investigations import interviews as IV


def test_transcript_parsing_formats():
    numbered = "1. ¿Quién usaba habitualmente el vehículo?\nSolamente yo.\n2. ¿Algo más\nque agregar?\nNo, nada más.\n"
    items = IV.parse_text(numbered)
    assert [(q.n, q.a) for q in items] == [(1, "Solamente yo."), (2, "No, nada más.")] and items[1].q == "¿Algo más que agregar?"
    pr = IV.parse_text("P: ¿Qué hizo el otro vehículo?\nR: Se fugó del lugar.\nP: ¿Hora?\nR: A las 10:40.")
    assert len(pr) == 2 and pr[0].a == "Se fugó del lugar."


def test_interview_contradictions_and_documents():
    iv1 = IV.Interview("Ana", "Asegurada", items=IV.parse_text(
        "1. ¿Quién usaba habitualmente el vehículo?\nLo usamos los dos, yo y también mi hijo.\n"
        "2. ¿Qué pasó con el otro vehículo?\nSe fugó de inmediato.\n3. ¿Su RUT?\n11.111.111-1."), prefix="aaaaaaaa", index=1)
    iv2 = IV.Interview("Luis", "Conductor", items=IV.parse_text(
        "1. ¿Quién utilizaba habitualmente el vehículo?\nSolamente yo.\n2. ¿El otro vehículo se detuvo?\nNo tengo más información, no puedo aclarar.\n"
        "3. ¿A qué hora ocurrió el siniestro?\nA las 10 de la mañana.\n4. ¿Kilometraje?\nTenía 29.000 kilómetros."), prefix="bbbbbbbb", index=2)
    f = IV.compare([iv1, iv2], "2026-09-11T10:40:00")
    rules = {x.rule for x in f}
    assert {"contradiction_usuario_habitual", "contradiction_otro_vehiculo", "contradiction_hora"} <= rules
    assert any(x.evidence == ["aaaaaaaa:1001", "bbbbbbbb:2001"] for x in f)
    doc = IV.doc_facts_from_text("nota.pdf", "cccccccc:1", "Kilometraje: 46.592 km. RUT vendedor: 25.984.979-9")
    d = {x.rule for x in IV.cross_documents([iv1, iv2], [doc])}
    assert d == {"km_mismatch", "third_party_docs"}
    # sin contradicción: mismos hechos contados igual
    iv3 = IV.Interview("Eva", "Testigo", items=IV.parse_text("1. ¿Quién usaba habitualmente el vehículo?\nSolamente yo."), index=3)
    assert not [x for x in IV.compare([iv2, iv3]) if x.rule == "contradiction_usuario_habitual"]


def test_audit_finds_seeded_errors_in_fictional_report():
    rep = RA.read_pdf(INV_DEMO / "informe_para_auditar.pdf")
    assert len(rep.interviews) == 2 and len(rep.alerts) == 4 and rep.recommendation == "SE RECOMIENDA RECHAZAR EL RECLAMO"
    rules = {f.rule for f in RA.audit(rep, "deadbeef")}
    assert {"internal_trayecto", "contradiction_usuario_habitual", "contradiction_otro_vehiculo", "transcript_role",
            "weak_rejection", "empty_row", "name_variants"} <= rules
    assert not any("Página" in qa.a for iv in rep.interviews for qa in iv.items)


def test_expediente_flow_review_and_report(tmp_path):
    work = tmp_path / "w"
    done = INV.load_demo(work)
    assert done[0] == "SIN-DEMO-4471" and done[1].startswith("AUD-")
    case = Case(work / "SIN-DEMO-4471")
    a = INV.analyze(case)
    assert {"km_mismatch", "third_party_docs", "contradiction_usuario_habitual"} <= {f.rule for f in a["findings"]}
    assert len(a["verified"].accepted) >= 5 and not a["verified"].rejected
    review = {r.rule for r in INV.review(a)}
    assert {"review_missing", "review_unaddressed", "review_weak_rejection"} <= review
    # completar el trabajo: responder todo citando las contradicciones y concluir con un hecho acreditado
    all_ev = [e for f in a["findings"] for e in f.evidence]
    for i in range(1, 5):
        INV.save_response(case, i, "Acreditado" if i == 4 else "Confirmado", "Hallazgo", all_ev, "Analista")
    INV.save_conclusion(case, "Rechazar el reclamo", "Kilometraje adulterado acreditado con la nota de venta.", "Analista")
    a = INV.analyze(case)
    assert INV.review(a) == []
    html = INV.build_report(case, a, "Consultora Prueba")
    assert "CONSULTORA PRUEBA" in html and "RESPUESTA A LAS ALERTAS" in html.upper() and "15/09/2026 16:45" in html
    assert verify_chain(case.ledger.entries())[0]
    actions = [e["action"] for e in case.ledger.entries()]
    assert actions.count("alert_response") >= 6 and "conclusion" in actions


def test_web_investigations(tmp_path):
    import io as _io
    c = web_client(tmp_path)
    assert "Aún no hay expedientes" in c.get("/investigaciones").get_data(as_text=True)
    c.post("/investigaciones/ejemplo")
    page = c.get("/investigacion/SIN-DEMO-4471").get_data(as_text=True)
    assert "Revisión previa" in page and "Qué dice cada declarante" in page and "E1·P9" in page
    r = c.post("/investigacion/SIN-DEMO-4471/alerta/2", data={"estado": "Acreditado", "hallazgo": "Bono confirma la atención",
                                                               "evidencia": ["x"], "actor": "Ana"}, follow_redirects=True)
    assert "Respuesta a la alerta 2 guardada" in r.get_data(as_text=True)
    assert "INFORME DE INVESTIGACIÓN" in c.get("/investigacion/SIN-DEMO-4471/informe").get_data(as_text=True)
    z = c.get("/investigacion/SIN-DEMO-4471/exportar")
    assert "verify.py" in zipfile.ZipFile(_io.BytesIO(z.data)).namelist()
    with open(INV_DEMO / "informe_para_auditar.pdf", "rb") as fh:
        r = c.post("/auditar", data={"actor": "Rev", "pdf": (fh, "informe.pdf")}, content_type="multipart/form-data", follow_redirects=True)
    assert "ya estaba auditado" in r.get_data(as_text=True) and "El informe se contradice" in r.get_data(as_text=True)
    r = c.post("/investigaciones/nuevo", data={"numero": "INV-1", "fecha_ocurrencia": "2026-09-01T10:00", "actor": "Ana",
                                              "alertas": "posible uso comercial", "iv_declarante": ["Uno", ""], "iv_rol": ["Asegurado", ""],
                                              "iv_fecha": ["", ""], "iv_texto": ["1. ¿Quién usaba habitualmente el vehículo?\nSolamente yo.", ""]},
               follow_redirects=True)
    assert "Expediente INV-1" in r.get_data(as_text=True)
