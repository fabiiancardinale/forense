"""El modelo aprendido es opcional, se verifica antes de cargarlo y sus alertas llegan al informe."""
import hashlib
import json

import numpy as np
import pytest
from PIL import Image

torch = pytest.importorskip("torch")
pytest.importorskip("onnxruntime")

from evidex.forensics import learned  # noqa: E402


class RedPatch(torch.nn.Module):
    """Modelo de juguete: «zona editada» = donde la imagen es muy roja."""

    def forward(self, x):
        m = torch.nn.functional.avg_pool2d(x[:, :1] - x[:, 1:2], 4)
        p = torch.sigmoid((m - 1.0) * 8)
        return p, p.flatten(1).topk(10, dim=1).values.mean(1)


def make_model(folder, licencia="CC BY 4.0", umbral=.5, side=128, tamper=False):
    folder.mkdir(parents=True, exist_ok=True)
    onnx = folder / "evidex_ia.onnx"
    torch.onnx.export(RedPatch(), (torch.zeros(1, 3, side, side),), str(onnx), input_names=["imagen"],
                      output_names=["mapa", "puntaje"], opset_version=17, dynamo=False)
    sha = hashlib.sha256(onnx.read_bytes()).hexdigest()
    card = {"formato": 1, "nombre": "prueba", "lado": side, "umbral": umbral, "sha256_onnx": sha,
            "conjuntos": [{"nombre": "TGIF", "licencia": licencia, "imagenes": 10}], "validacion": {}}
    (folder / "evidex_ia.json").write_text(json.dumps(card))
    if tamper:
        onnx.write_bytes(onnx.read_bytes() + b"x")
    return folder


def photo(path, red=True):
    a = np.full((480, 640, 3), 120, np.uint8)
    a += np.random.default_rng(1).integers(0, 20, a.shape, dtype=np.uint8)
    if red:
        a[300:420, 400:560] = (250, 10, 10)
    Image.fromarray(a).save(path, "JPEG", quality=85)
    return path


@pytest.fixture
def model_env(tmp_path, monkeypatch):
    d = tmp_path / "modelos"
    monkeypatch.setenv("EVIDEX_MODELO", str(d))
    learned._cache.clear()
    yield d
    learned._cache.clear()


def test_without_model_nothing_changes(model_env, tmp_path):
    from evidex.inspection.pipeline import analyze
    assert learned.check(photo(tmp_path / "a.jpg")) == {} and not learned.available()
    res = analyze(tmp_path / "a.jpg", "a.jpg", tmp_path)
    det = {d["name"]: d["status"] for d in res["detectors"]}
    assert det["localización aprendida"] == "not_run"
    assert not [f for f in res["findings"] if f["rule"] == "ai_model_region"]


def test_model_flags_zone_and_reaches_report(model_env, tmp_path):
    from evidex.inspection.pipeline import analyze
    make_model(model_env)
    assert learned.available() and learned.status()["id"]
    r = learned.check(photo(tmp_path / "rojo.jpg"))
    assert r["flag"] and r["score"] > .5
    x0, y0, x1, y1 = r["region"]["bbox"]
    assert 360 <= x0 <= 420 and 270 <= y0 <= 320 and x1 >= 540 and y1 >= 400, r   # la zona roja
    assert not learned.check(photo(tmp_path / "gris.jpg", red=False))["flag"]
    res = analyze(tmp_path / "rojo.jpg", "IMG-20260920-WA0001.jpg", tmp_path)
    f = [f for f in res["findings"] if f["rule"] == "ai_model_region"]
    assert f and f[0]["evidence_type"] == "model" and not f[0]["confirmed_change"] and f[0]["why"]
    assert {d["name"]: d["status"] for d in res["detectors"]}["localización aprendida"] == "completed"
    assert any(a["file"] == "regions.png" for a in res["artifacts"])           # zona dibujada para el analista


@pytest.mark.parametrize("kw,reason", [({"licencia": "CC BY-NC 4.0"}, "licencia"),
                                       ({"licencia": ""}, "licencia"),
                                       ({"tamper": True}, "sha256")])
def test_model_refused_when_unsafe(model_env, tmp_path, kw, reason):
    make_model(model_env, **kw)
    st = learned.status()
    assert not st["available"] and reason in st["reason"]
    assert learned.check(photo(tmp_path / "rojo.jpg")) == {}


def test_installing_a_model_asks_to_reanalyze_claims(model_env, tmp_path):
    from types import SimpleNamespace
    from evidex.web.common import analysis_mark
    case = SimpleNamespace(ledger=SimpleNamespace(entries=lambda: [{"action": "evidence_added"}]))
    before = analysis_mark(case)
    make_model(model_env)
    assert analysis_mark(case) != before and analysis_mark(case).endswith(learned.model_id())
