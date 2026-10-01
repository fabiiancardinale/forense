"""Núcleo: cadena de custodia, firma, paquete verificable y asistente con citas."""
import json
import subprocess
import sys
import zipfile


from helpers import UTF8_ENV
from veritas.cli import main
from veritas.core import assistant, detections
from veritas.core.case import Case
from veritas.core.ledger import verify_chain
from veritas.core.timeline import Timeline


def test_detects_full_attack_chain(built):
    tl = Timeline(built / "timeline.db")
    rules = {f.rule for f in detections.run_all(tl.all())}
    assert {"brute_force_success", "encoded_powershell", "admin_added", "service_installed", "log_cleared"} <= rules


def test_ledger_tamper_is_detected(built):
    case = Case(built)
    assert verify_chain(case.ledger.entries())[0]
    lines = (built / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    e = json.loads(lines[1]); e["actor"] = "otro"
    lines[1] = json.dumps(e)
    (built / "ledger.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert not verify_chain(Case(built).ledger.entries())[0]


def test_evidence_tamper_is_detected(built):
    case = Case(built)
    f = next(case.evidence_dir.iterdir())
    f.chmod(0o644); f.write_text("manipulado", encoding="utf-8")
    ok, problems = case.verify_evidence()
    assert not ok and problems


def test_assistant_rejects_ungrounded_claims(built):
    tl = Timeline(built / "timeline.db")
    real = tl.all()[0]["id"]
    text = f"Hubo un acceso [ev:{real}]. El atacante robó la base de datos. Hecho falso [ev:deadbeef:999]."
    v = assistant.verify_claims(text, tl)
    assert len(v.accepted) == 1 and len(v.rejected) == 2


def test_export_bundle_verifies_and_detects_tamper(built, tmp_path):
    z = tmp_path / "paquete.zip"
    main(["report", str(built)])
    main(["export", str(built), str(z)])
    out = tmp_path / "pkg"
    zipfile.ZipFile(z).extractall(out)
    r = subprocess.run([sys.executable, str(out / "verify.py")], capture_output=True, text=True, encoding="utf-8", env=UTF8_ENV)
    assert r.returncode == 0, r.stdout
    assert "firma digital válida" in r.stdout
    # alterar una entrada y volver a verificar
    led = out / "ledger.jsonl"
    led.write_text(led.read_text(encoding="utf-8").replace("case_created", "case_deleted"), encoding="utf-8")
    r = subprocess.run([sys.executable, str(out / "verify.py")], capture_output=True, text=True, encoding="utf-8", env=UTF8_ENV)
    assert r.returncode == 1


def test_offline_summary_keeps_claims(built):
    tl = Timeline(built / "timeline.db")
    v = assistant.summarize(detections.run_all(tl.all()), tl)
    assert len(v.accepted) >= 5 and not v.rejected
    assert all(assistant.CITE.sub("", s).strip(" .") for s in v.accepted)
