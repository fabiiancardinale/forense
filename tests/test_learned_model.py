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


def make_model(folder, licencia="CC BY 4.0", umbral=.5, side=128, tamper=False, mosaico=False):
    folder.mkdir(parents=True, exist_ok=True)
    onnx = folder / "evidex_ia.onnx"
    torch.onnx.export(RedPatch(), (torch.zeros(1, 3, side, side),), str(onnx), input_names=["imagen"],
                      output_names=["mapa", "puntaje"], opset_version=17, dynamo=False)
    sha = hashlib.sha256(onnx.read_bytes()).hexdigest()
    card = {"formato": 1, "nombre": "prueba", "lado": side, "umbral": umbral, "sha256_onnx": sha,
            "conjuntos": [{"nombre": "TGIF", "licencia": licencia, "imagenes": 10}], "validacion": {}}
    if mosaico:
        card.update(formato=2, modo="mosaico", paso=side * 3 // 4, max_lado=2048)
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


def big_photo_small_edit(path):
    """Foto grande de celular con una edición chica (60 x 60 px): al achicar la foto a 128 px desaparece."""
    a = np.full((1500, 2000, 3), 120, np.uint8)
    a += np.random.default_rng(2).integers(0, 20, a.shape, dtype=np.uint8)
    a[1100:1160, 1500:1560] = (250, 10, 10)
    Image.fromarray(a).save(path, "JPEG", quality=90)
    return path


def test_mosaic_finds_small_edit_that_shrinking_misses(model_env, tmp_path):
    foto = big_photo_small_edit(tmp_path / "IMG-20261005-WA0003.jpg")
    make_model(model_env)                                     # formato 1: foto entera achicada
    assert not learned.check(foto)["flag"]
    learned._cache.clear()
    make_model(model_env, mosaico=True)                       # formato 2: mosaico a tamaño real
    r = learned.check(foto)
    assert r["flag"], r
    x0, y0, x1, y1 = r["region"]["bbox"]
    assert 1460 <= x0 <= 1510 and 1060 <= y0 <= 1110 and 1550 <= x1 <= 1600 and 1150 <= y1 <= 1200, r
    assert x1 - x0 < 200 and y1 - y0 < 200                    # marca la zona, no la foto entera
    gris = tmp_path / "gris.jpg"
    Image.fromarray(np.full((1500, 2000, 3), 120, np.uint8)).save(gris, "JPEG")
    assert not learned.check(gris)["flag"]


def test_training_and_evidex_use_the_same_mosaic(tmp_path):
    """El umbral se calibra con el mosaico del entrenamiento: tiene que dar lo mismo que el de Evidex."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))
    import datos
    red = RedPatch().eval()

    def run(t):
        with torch.no_grad():
            m, s = red(torch.from_numpy(t))
        return m.numpy(), s.numpy()
    for size in ((2000, 1500), (700, 500), (100, 90)):           # grande, mediana y más chica que un pedazo
        img = Image.open(big_photo_small_edit(tmp_path / "f.jpg")).resize(size)
        a = datos.puntuar_mosaico(run, datos.preparar(img), 128, 96)
        b = learned._mosaic_score(run, learned._prepare(img, 2048), 128, 96)
        assert abs(a[0] - b[0]) < 1e-6 and np.allclose(a[1], b[1]) and a[2] == b[2]


def test_training_crops_follow_the_edited_zone(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))
    import datos
    img = big_photo_small_edit(tmp_path / "e.png")
    mask = np.zeros((1500, 2000), np.uint8)
    mask[1100:1160, 1500:1560] = 255
    Image.fromarray(mask).save(tmp_path / "m.png")
    filas = [{"ruta": str(img), "etiqueta": 1, "mascara": str(tmp_path / "m.png")}] * 40
    ds = datos.Recortes(filas, 256)
    out = [ds[i] for i in range(40)]
    assert all(x.shape == (3, 256, 256) and m.shape == (1, 256, 256) for x, m, _ in out)
    con_zona = sum(y for _, _, y in out)
    assert 12 <= con_zona <= 36, con_zona                      # la mayoría sobre la zona, pero no todos
    assert all((m.sum() > 0) == bool(y) for _, m, y in out)     # la etiqueta es del recorte
