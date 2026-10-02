"""Análisis de siniestros: demo completa, reglas, informe y línea de comandos."""
import json
import subprocess
import sys
import zipfile

import pytest

from helpers import ACTUAL, LIMPIO, UTF8_ENV, analysis_of
from evidex.claims import analysis as claims
from evidex.claims import service
from evidex.cli import main
from evidex.core.case import Case
from evidex.core.ledger import verify_chain
from evidex.forensics import narrative, network, policy


def test_demo_loads_in_order_with_expected_outcome(loaded):
    _, r = loaded
    assert list(r) == ["SIN-2026-0412", "SIN-2026-0533", "SIN-2026-0601", ACTUAL, LIMPIO]
    assert r[ACTUAL]["level"] == "bad" and r[ACTUAL]["linked"] == 3 and r[ACTUAL]["score"] == 100
    assert r[LIMPIO]["findings"] == 0 and r[LIMPIO]["level"] == "ok"
    assert r["SIN-2026-0533"]["level"] == "bad"  # misma cuenta y relato copiado del 0412
    # al aparecer los siniestros nuevos, los históricos vinculados se reanalizaron
    assert r["SIN-2026-0533"]["reanalyzed"] == ["SIN-2026-0412"]
    assert set(r[ACTUAL]["reanalyzed"]) == {"SIN-2026-0412", "SIN-2026-0533", "SIN-2026-0601"}
    work = loaded[0]
    last = service.last_analysis(Case(work / "SIN-2026-0601"))
    assert last["level"] == "bad" and last["trigger"] == f"reanálisis por vínculo con {ACTUAL}"
    assert service.last_analysis(Case(work / LIMPIO))["level"] == "ok"


def test_suspicious_claim_triggers_every_module(loaded):
    work, _ = loaded
    findings = analysis_of(work, ACTUAL)[4]
    rules = {f.rule for f in findings}
    expected = {
        "edited", "reused_photo", "no_metadata", "ai_generated", "taken_before", "gps_mismatch",       # fotos
        "doc_editor", "doc_modified", "doc_before_claim", "reused_doc",                                 # documentos
        "coverage_change", "early_claim", "late_report", "near_limit",                                  # póliza
        "copied_narrative", "time_contradiction", "police_missing",                                     # relato
        "shared_contact", "fraud_ring",                                                                 # red
        "doc_version_changed", "doc_rut_invalid",                                                       # versiones y RUT
        "impossible_travel", "photo_before_policy",                                                     # línea de tiempo
        "chat_before_event", "chat_script", "chat_deleted", "chat_phone_link",                          # chat
    }
    assert expected <= rules, expected - rules
    assert not any("01_trasera" in f.title for f in findings)  # la foto legítima no se marca
    assert {f.category for f in findings} == {"Fotos", "Documentos", "Póliza y siniestro", "Relato", "Red de siniestros",
                                              "Línea de tiempo", "Comunicaciones", "Datos del asegurado"}


def test_clean_claim_has_no_alerts(loaded):
    work, _ = loaded
    assert analysis_of(work, LIMPIO)[4] == []
    assert "Sin alertas" in (work / LIMPIO / "informe.html").read_text(encoding="utf-8")


def test_report_has_network_and_grounded_summary(loaded):
    work, _ = loaded
    html = (work / ACTUAL / "informe.html").read_text(encoding="utf-8")
    assert '<svg class="net"' in html and "SIN-2026-0601" in html
    assert "0 afirmación(es) sin evidencia" in html
    for section in ("Red de siniestros", "Póliza y siniestro", "Documentos", "Relato del asegurado"):
        assert section in html


def test_export_bundle_of_claim_verifies(loaded, tmp_path):
    work, _ = loaded
    z = tmp_path / "s.zip"
    main(["export", str(work / ACTUAL), str(z)])
    zipfile.ZipFile(z).extractall(tmp_path / "pkg")
    r = subprocess.run([sys.executable, str(tmp_path / "pkg/verify.py")], capture_output=True, text=True, encoding="utf-8", env=UTF8_ENV)
    assert r.returncode == 0, r.stdout
    assert "presupuesto_taller.pdf" in r.stdout


def test_only_the_intended_photo_is_a_duplicate(demo_src):
    from PIL import Image
    fs = sorted(demo_src.rglob("fotos/*"))
    hs = {f.name: claims.dhash(Image.open(f)) for f in fs}
    close = {tuple(sorted((a, b))) for a in hs for b in hs if a < b and claims.hamming(hs[a], hs[b]) <= claims.DUP_MAX_DISTANCE}
    assert close == {("03_parachoques.jpg", "IMG_4471.jpg")}


def test_policy_rules_and_amount_parsing():
    assert policy.parse_amount("$4.650.000") == 4650000 == policy.parse_amount("4650000.0") == policy.parse_amount(4650000)
    base = {"numero": "X", "fecha_siniestro": "2026-09-20T03:00:00"}
    rules = {f.rule for f in policy.analyze({**base, "inicio_poliza": "2026-09-25", "fecha_denuncia": "2026-11-30"}, "e:1")}
    assert {"before_policy", "late_report", "night_no_witness"} <= rules
    calm = {**base, "fecha_siniestro": "2026-09-20T15:00:00", "inicio_poliza": "2024-01-01", "fin_poliza": "2027-01-01",
            "fecha_denuncia": "2026-09-21", "suma_asegurada": "5.000.000", "monto_reclamado": "900.000"}
    assert policy.analyze(calm, "e:1") == []


def test_narrative_copy_and_contradictions():
    a = "Estaba detenido en el semáforo cuando un auto me chocó por detrás y se dio a la fuga sin dejar sus datos."
    b = "Me encontraba detenido en el semáforo cuando un auto me chocó por detrás y se dio a la fuga sin dejar datos."
    c = "Al salir del estacionamiento del supermercado otro vehículo retrocedió y golpeó la puerta del conductor."
    assert narrative.similarity(a, b) > 0.5 > narrative.similarity(a, c)
    decl = {"numero": "N", "fecha_siniestro": "2026-01-01T14:00:00", "testigos": 2,
            "descripcion": "Ocurrió en la noche, no hubo testigos y dejé constancia en Carabineros de lo que pasó ese día."}
    rules = {f.rule for f in narrative.analyze(decl, "e:1", {"OTRO": {"relato": decl["descripcion"]}})}
    assert {"copied_narrative", "time_contradiction", "witness_contradiction", "police_missing"} <= rules


def test_network_normalization_and_same_person_is_not_a_ring():
    assert network.normalize("rut", "12.345.678-k") == "12345678K"
    assert network.normalize("telefono", "+56 9 4444 9090") == network.normalize("telefono", "944449090")
    # el mismo asegurado con varios siniestros: frecuencia sí, red de personas distintas no
    reg = [network.claim_record({"numero": f"S{i}", "rut": "11.111.111-1", "telefono": "+56 9 1111 2222",
                                 "fecha_siniestro": f"2026-0{i}-10T10:00:00"}, "ok") for i in (3, 5, 7)]
    decl = {"numero": "S9", "rut": "11111111-1", "telefono": "91111 2222", "fecha_siniestro": "2026-09-10T10:00:00"}
    f, net = network.analyze(decl, "e:1", [], [], reg)
    assert {x.rule for x in f} == {"frequency_rut"} and net["group"] == []


def test_cli_accepts_pdf_and_rejects_other_files(demo_src, tmp_path):
    src = demo_src / "limpio"
    case = tmp_path / "c"
    main(["siniestro-init", str(case), str(src / "declaracion.json"), str(src / "fotos/a_frontal.jpg"),
          str(src / "documentos/presupuesto_automotriz_central.pdf")])
    main(["siniestro-analizar", str(case)])
    assert "presupuesto_automotriz_central.pdf" in (case / "informe.html").read_text(encoding="utf-8")
    (tmp_path / "nota.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit, match="no son fotos ni PDF"):
        main(["siniestro-init", str(tmp_path / "d"), str(src / "declaracion.json"), str(tmp_path / "nota.txt")])


def test_declaration_saved_as_windows_ansi_is_accepted(demo_src, tmp_path):
    decl = json.loads((demo_src / "limpio/declaracion.json").read_text(encoding="utf-8"))
    ansi = tmp_path / "decl_ansi.json"
    ansi.write_bytes(json.dumps(decl, ensure_ascii=False).encode("cp1252"))  # como el Bloc de notas
    case = tmp_path / "ansi"
    main(["siniestro-init", str(case), str(ansi), str(demo_src / "limpio/fotos/a_frontal.jpg")])
    main(["siniestro-analizar", str(case)])
    assert "camión de reparto" in (case / "informe.html").read_text(encoding="utf-8")


def test_clear_errors_for_missing_or_duplicate_case(demo_src, tmp_path):
    decl = str(demo_src / "limpio/declaracion.json")
    with pytest.raises(SystemExit, match="No existe el caso"):
        main(["siniestro-analizar", str(tmp_path / "no_existe")])
    main(["siniestro-init", str(tmp_path / "dup"), decl])
    with pytest.raises(SystemExit, match="ya existe"):
        main(["siniestro-init", str(tmp_path / "dup"), decl])
    with pytest.raises(SystemExit, match="No se encuentra"):
        main(["siniestro-init", str(tmp_path / "x"), str(tmp_path / "falta.json")])


def test_forensic_timeline_in_report_and_web(loaded):
    work, _ = loaded
    html = (work / ACTUAL / "informe.html").read_text(encoding="utf-8")
    assert "Línea de tiempo forense" in html and "traslado imposible" in html and "chat·" in html
    assert "qué cambió de la versión 1" in html and "$1.850.000" in html
    from evidex.web import create_app
    c = create_app(work).test_client()
    case = service.find_case(work, ACTUAL)
    digest = next(e["subject"] for e in case.ledger.entries()
                  if e["action"] == "evidence_added" and e["data"]["original_name"] == "presupuesto_taller.pdf")
    r = c.get(f"/caso/{case.root.name}/documento/{digest}/version/1")
    assert r.status_code == 200 and r.data.startswith(b"%PDF") and r.data.count(b"%%EOF") == 1
    assert c.get(f"/caso/{case.root.name}/documento/{digest}/version/9").status_code == 404
    assert c.get(f"/caso/{case.root.name}/documento/{'0' * 64}/version/1").status_code == 404


def test_report_findings_show_thumbnail_and_guidance(loaded):
    work, _ = loaded
    html = (work / ACTUAL / "informe.html").read_text(encoding="utf-8")
    assert 'class="finding alta withpic"' in html and 'class="fthumb"' in html
    assert "Por qué importa:" in html and "Qué hacer:" in html


def test_decisions_are_in_custody_and_feed_metrics(tmp_path, demo_src):
    work = tmp_path / "w"
    service.load_demo(work)
    case = Case(work / ACTUAL)
    service.set_decision(case, "fraude", "Liquidador Prueba", "Confirmado con el taller")
    service.set_decision(Case(work / LIMPIO), "legitimo", "Liquidador Prueba")
    assert service.current_decision(case)["actor"] == "Liquidador Prueba"
    assert verify_chain(case.ledger.entries())[0]
    m = service.metrics(work)
    assert (m["tp"], m["tn"], m["fp"], m["fn"]) == (1, 1, 0, 0)
    with pytest.raises(ValueError):
        service.set_decision(case, "inventada", "x")
