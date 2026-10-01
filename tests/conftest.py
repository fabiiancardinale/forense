"""Datos de prueba compartidos: se generan una vez por sesión (son ficticios)."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from veritas.claims import importer, service  # noqa: E402
from veritas.cli import main  # noqa: E402


@pytest.fixture
def built(tmp_path):
    """Caso de incidente informático con la cadena de ataque de ejemplo."""
    subprocess.run([sys.executable, str(ROOT / "demo/make_demo.py"), str(tmp_path / "ev.jsonl")], check=True, capture_output=True)
    case_dir = tmp_path / "caso"
    main(["init", str(case_dir), "Incidente demo"])
    main(["add", str(case_dir), str(tmp_path / "ev.jsonl")])
    main(["ingest", str(case_dir)])
    return case_dir


@pytest.fixture(scope="session")
def demo_src(tmp_path_factory):
    """Archivos de la demo de siniestros (fotos, PDF, chats), sin cargar."""
    d = tmp_path_factory.mktemp("demo") / "src"
    subprocess.run([sys.executable, str(ROOT / "demo/make_claim_demo.py"), str(d)], check=True, capture_output=True)
    return d


@pytest.fixture(scope="session")
def loaded(tmp_path_factory):
    """Demo de siniestros cargada y analizada en una carpeta de casos."""
    work = tmp_path_factory.mktemp("work") / "casos"
    results = dict(service.load_demo(work))
    return work, results


@pytest.fixture(scope="session")
def history(tmp_path_factory):
    """Historial de siniestros de ejemplo importado."""
    d = tmp_path_factory.mktemp("hist")
    csv_path = d / "historial.csv"
    subprocess.run([sys.executable, str(ROOT / "demo/make_history_demo.py"), str(csv_path)], check=True, capture_output=True)
    work = d / "casos"
    return work, csv_path, importer.import_history(work, csv_path, actor="prueba")
