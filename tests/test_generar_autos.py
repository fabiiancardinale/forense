"""Generador de fotos de autos editadas con IA: máscaras exactas, la foto solo cambia dentro de la máscara y el
resultado entra directo al entrenamiento con su licencia."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))
import datos            # noqa: E402
import generar_autos    # noqa: E402


def _supervisely(raiz: Path, nombre: str, objetos: list[tuple[str, list]]):
    (raiz / "img").mkdir(parents=True, exist_ok=True)
    (raiz / "ann").mkdir(parents=True, exist_ok=True)
    a = np.full((480, 640, 3), 90, np.uint8)
    a += np.random.default_rng(len(nombre)).integers(0, 40, a.shape, dtype=np.uint8)
    Image.fromarray(a).save(raiz / "img" / nombre, "JPEG", quality=90)
    ann = {"size": {"height": 480, "width": 640},
           "objects": [{"classTitle": c, "geometryType": "polygon", "points": {"exterior": p, "interior": []}}
                       for c, p in objetos]}
    (raiz / "ann" / f"{nombre}.json").write_text(json.dumps(ann))


class Pintor:
    """Editor falso: pinta de verde todo lo que recibe (para ver exactamente qué zona cambió)."""
    lado = 256

    def __init__(self):
        self.llamadas = []

    def __call__(self, img, mask, prompt, semilla):
        self.llamadas.append((img.size, prompt))
        return Image.new("RGB", img.size, (0, 255, 0))


def test_generates_edits_only_inside_mask_and_feeds_training(tmp_path):
    hitl = tmp_path / "hitl" / "Car damages dataset" / "File1"
    _supervisely(hitl, "Car damages 1.jpg", [("Dent", [[300, 200], [360, 200], [360, 250], [300, 250]]),
                                              ("Front-door", [[200, 120], [460, 120], [460, 380], [200, 380]])])
    _supervisely(hitl, "Car damages 2.jpg", [("Fender", [[100, 100], [300, 100], [300, 300], [100, 300]]),
                                              ("Headlight", [[400, 300], [480, 300], [480, 340], [400, 340]])])
    items = generar_autos.listar(tmp_path / "hitl")
    assert len(items) == 2
    lama, sdxl = Pintor(), Pintor()
    sal = tmp_path / "autos_ia"
    n = generar_autos.generar(items, sal, {"sdxl": sdxl, "lama": lama}, semilla=1)
    reg = [json.loads(x) for x in (sal / "registro.jsonl").read_text().splitlines()]
    assert n == len(reg) >= 3 and {r["tipo"] for r in reg} >= {"borrar_dano", "agregar_dano"}
    assert all(r["editor"] in ("sdxl", "lama") for r in reg) and all(r["prompt"] for r in reg)
    for r in reg:
        ed = np.asarray(Image.open(sal / "editadas" / r["editada"]).convert("RGB")).astype(int)
        orig = np.asarray(Image.open(sal / "originales" / r["original"]).convert("RGB")).astype(int)
        m = np.asarray(Image.open(sal / "mascaras" / r["editada"])) > 0
        assert m.any() and ed.shape == orig.shape
        verde = (ed[..., 1] > 200) & (ed[..., 0] < 60)
        from PIL import ImageFilter
        centro = np.asarray(Image.fromarray(m.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(15))) > 0
        assert centro.any() and verde[centro].mean() > .98                 # dentro de la zona: lo que hizo el editor (borde suave)
        assert np.abs(ed[~m] - orig[~m]).max() == 0       # fuera de la máscara: la foto original intacta
    # retomar no rehace lo que ya está
    assert generar_autos.generar(items, sal, {"sdxl": sdxl, "lama": lama}, semilla=1) == 0
    # entra al entrenamiento como fotos propias, con su licencia (uso comercial permitido)
    filas = datos.manifiesto_propias(sal)
    assert sum(f["etiqueta"] == 0 for f in filas) == 2 and sum(f["etiqueta"] for f in filas) == n
    assert all(f["mascara"] for f in filas if f["etiqueta"]) and "CC0" in filas[0]["licencia"]
    assert all(datos.licencia_permitida(f["licencia"]) and datos.es_vehiculo(f) for f in filas)
    entren, val = datos.dividir(filas * 1, val=.5, semilla=3)
    base = lambda f: Path(f["ruta"]).name.split("_")[0].split(".")[0]           # noqa: E731
    assert not ({base(f) for f in entren} & {base(f) for f in val})             # original y sus ediciones juntas


def test_split_shards_photos_between_gpus(tmp_path):
    hitl = tmp_path / "hitl"
    for i in range(4):
        _supervisely(hitl, f"Car parts {i}.jpg", [("Hood", [[100, 100], [400, 100], [400, 300], [100, 300]])])
    items = generar_autos.listar(hitl)
    a = generar_autos.generar(items, tmp_path / "s", {"kandinsky": Pintor()}, parte=0, partes=2)
    b = generar_autos.generar(items, tmp_path / "s", {"kandinsky": Pintor()}, parte=1, partes=2)
    assert a == b == 2 and len(list((tmp_path / "s" / "originales").iterdir())) == 4
