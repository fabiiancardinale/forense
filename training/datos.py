"""Datos para entrenar el detector de ediciones con IA.

Todo pasa por un manifiesto CSV (una fila por imagen), para saber siempre de dónde salió cada foto y con qué
licencia:  ruta,etiqueta,mascara,conjunto,licencia
  etiqueta: 1 = editada/generada con IA, 0 = original
  mascara: PNG blanco donde se cambió (vacío = sin máscara; para originales se usa todo negro)

Conjuntos soportados de entrada:
  - TGIF / TGIF2 (carpetas orig/, sd2-sp/, sdxl-fr/, ... y masks/), CC BY 4.0 / CC BY-SA 4.0.
  - Fotos propias (carpeta con originales/ y editadas/, y opcionalmente mascaras/ con el mismo nombre).
    Use solo fotos suyas o con permiso escrito; los datos reales de BCI requieren autorización de BCI.

Las licencias NO comerciales quedan bloqueadas: el script se niega a usarlas (ver LICENCIAS_BLOQUEADAS).
"""
from __future__ import annotations

import csv
import io
import random
import re
from pathlib import Path

import numpy as np
from PIL import Image

IMAGES = {".jpg", ".jpeg", ".png", ".webp"}
LICENCIAS_BLOQUEADAS = ("nc", "non-commercial", "noncommercial", "no comercial", "research only", "desconocida")
CAMPOS = ["ruta", "etiqueta", "mascara", "conjunto", "licencia"]

# subcarpeta de TGIF -> licencia (README de IDLabMedia/tgif-dataset)
TGIF_LICENCIA = "CC BY 4.0 (TGIF) / CC BY-SA 4.0 (TGIF2); imágenes base MS-COCO"
TGIF_EVITAR = ("flux",)          # FLUX.1 dev tiene licencia no comercial: esas imágenes no se usan


def licencia_permitida(lic: str) -> bool:
    l = (lic or "desconocida").lower()
    return not any(b in l for b in LICENCIAS_BLOQUEADAS)


def _mascara_tgif(img: Path, masks: Path) -> str:
    # «368961_mask_bbox.png_ps_mask.png_sd2_0.png» -> masks/<split>/<clase>/368961_mask_bbox.png
    m = re.match(r"(.+?_mask_(?:bbox|segm)(?:_512)?\.png)", img.name)
    if not m:
        return ""
    rel = img.parent.relative_to(img.parents[2])           # <split>/<clase>
    cand = masks / rel / m.group(1)
    return str(cand) if cand.exists() else ""


def manifiesto_tgif(raiz: Path) -> list[dict]:
    """raiz/orig/<split>/<clase>/*.png, raiz/<metodo>/<split>/<clase>/*.png, raiz/masks/..."""
    filas, masks = [], raiz / "masks"
    for carpeta in sorted(p for p in raiz.iterdir() if p.is_dir() and p.name != "masks"):
        if any(x in carpeta.name.lower() for x in TGIF_EVITAR):
            continue
        original = carpeta.name == "orig"
        for img in sorted(p for p in carpeta.rglob("*") if p.suffix.lower() in IMAGES):
            mask = "" if original else _mascara_tgif(img, masks)
            if not original and not mask:
                continue                                     # editada sin máscara: no sirve para localizar
            filas.append({"ruta": str(img), "etiqueta": 0 if original else 1, "mascara": mask,
                          "conjunto": f"TGIF/{carpeta.name}", "licencia": TGIF_LICENCIA})
    return filas


def manifiesto_propias(raiz: Path, licencia: str = "propia (fotos de Zelekpress con permiso)") -> list[dict]:
    filas = []
    for sub, et in (("originales", 0), ("editadas", 1)):
        for img in sorted(p for p in (raiz / sub).rglob("*") if p.suffix.lower() in IMAGES):
            mask = raiz / "mascaras" / (img.stem + ".png")
            filas.append({"ruta": str(img), "etiqueta": et, "mascara": str(mask) if mask.exists() else "",
                          "conjunto": f"propias/{sub}", "licencia": licencia})
    return filas


def guardar(filas: list[dict], destino: Path) -> None:
    malas = sorted({f["licencia"] for f in filas if not licencia_permitida(f["licencia"])})
    if malas:
        raise SystemExit(f"Licencias no permitidas para uso comercial: {malas}")
    with destino.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(filas)


def leer(manifiesto: Path) -> list[dict]:
    with manifiesto.open(encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    for f in filas:
        if not licencia_permitida(f["licencia"]):
            raise SystemExit(f"{f['ruta']}: licencia no permitida ({f['licencia']})")
        f["etiqueta"] = int(f["etiqueta"])
    return filas


# ---- lo que le pasa a una foto en el camino (WhatsApp, capturas, reenvíos) -------------------------------
def como_whatsapp(img: Image.Image, mask: Image.Image, rng: random.Random) -> tuple[Image.Image, Image.Image]:
    """Reducción + recompresión JPEG (a veces doble) + recorte leve. Se aplica IGUAL a originales y editadas,
    para que el modelo no aprenda «comprimida = editada»."""
    if rng.random() < .3:                                   # recorte leve, como al reencuadrar en la galería
        w, h = img.size
        dx, dy = int(w * rng.uniform(0, .08)), int(h * rng.uniform(0, .08))
        box = (dx, dy, w - int(w * rng.uniform(0, .08)), h - int(h * rng.uniform(0, .08)))
        img, mask = img.crop(box), mask.crop(box)
    lado = rng.choice([640, 800, 1024, 1280, 1600, 2048])
    if max(img.size) > lado:
        f = lado / max(img.size)
        nuevo = (max(1, round(img.width * f)), max(1, round(img.height * f)))
        img, mask = img.resize(nuevo, Image.LANCZOS), mask.resize(nuevo, Image.NEAREST)
    for _ in range(rng.choice([1, 1, 2])):                  # a veces se reenvía: doble compresión
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=rng.randint(50, 92))
        img = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    return img, mask


def a_tensor(img: Image.Image, lado: int) -> np.ndarray:
    """Igual que en evidex/forensics/learned.py: RGB, lado x lado, 0..1, normalizado ImageNet, CHW."""
    x = np.asarray(img.convert("RGB").resize((lado, lado), Image.BILINEAR), dtype=np.float32) / 255.0
    x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    return x.transpose(2, 0, 1)


class Conjunto:
    """Dataset compatible con torch.utils.data (sin depender de torch aquí)."""

    def __init__(self, filas: list[dict], lado: int = 512, aumentar: bool = True, semilla: int = 0):
        self.filas, self.lado, self.aumentar, self.semilla = filas, lado, aumentar, semilla
        self.epoca = 0

    def __len__(self):
        return len(self.filas)

    def __getitem__(self, i):
        f = self.filas[i]
        rng = random.Random(hash((self.semilla, self.epoca if self.aumentar else 0, i)))
        img = Image.open(f["ruta"]).convert("RGB")
        if f["mascara"]:
            mask = Image.open(f["mascara"]).convert("L").resize(img.size, Image.NEAREST)
        else:
            mask = Image.new("L", img.size, 255 if (f["etiqueta"] and not f["mascara"]) else 0)
        img, mask = como_whatsapp(img, mask, rng)
        if self.aumentar and rng.random() < .5:
            img, mask = img.transpose(Image.FLIP_LEFT_RIGHT), mask.transpose(Image.FLIP_LEFT_RIGHT)
        m = (np.asarray(mask.resize((self.lado, self.lado), Image.NEAREST)) > 127).astype(np.float32)
        return a_tensor(img, self.lado), m[None], np.float32(f["etiqueta"])


def dividir(filas: list[dict], val: float = .15, semilla: int = 0) -> tuple[list[dict], list[dict]]:
    """Separa por imagen base (id COCO / nombre), para que la original y su edición no queden una en
    entrenamiento y otra en validación (eso inflaría las métricas)."""
    def base(f):
        return re.match(r"(\d+|[^_.]+)", Path(f["ruta"]).name).group(1)
    ids = sorted({base(f) for f in filas})
    random.Random(semilla).shuffle(ids)
    v = set(ids[:max(1, int(len(ids) * val))])
    return [f for f in filas if base(f) not in v], [f for f in filas if base(f) in v]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Crea el manifiesto CSV de entrenamiento.")
    ap.add_argument("--tgif", type=Path, action="append", default=[], help="carpeta raíz de TGIF/TGIF2")
    ap.add_argument("--propias", type=Path, action="append", default=[], help="carpeta con originales/ y editadas/")
    ap.add_argument("--salida", type=Path, default=Path("manifiesto.csv"))
    a = ap.parse_args()
    filas = [f for r in a.tgif for f in manifiesto_tgif(r)] + [f for r in a.propias for f in manifiesto_propias(r)]
    guardar(filas, a.salida)
    print(f"{len(filas)} imágenes ({sum(f['etiqueta'] for f in filas)} editadas) -> {a.salida}")
