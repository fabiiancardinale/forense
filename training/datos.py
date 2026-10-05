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
        # «-fr» = toda la imagen pasó por la IA (regenerada): la máscara es la imagen completa, no solo la zona
        completa = carpeta.name.lower().endswith("-fr")
        for img in sorted(p for p in carpeta.rglob("*") if p.suffix.lower() in IMAGES):
            mask = "" if original or completa else _mascara_tgif(img, masks)
            if not original and not completa and not mask:
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


# ---- mosaico: la foto se analiza en pedazos a tamaño real, sin achicarla a 512 ----------------------------
# (la misma lógica está en evidex/forensics/learned.py; tests/test_learned_model.py revisa que den lo mismo)
MAX_LADO = 2048          # fotos más grandes se reducen a esto antes del mosaico (tiempo de análisis acotado)


def posiciones(n: int, lado: int, paso: int) -> list[int]:
    if n <= lado:
        return [0]
    pos = list(range(0, n - lado, paso))
    return pos + [n - lado]


def preparar(img: Image.Image, max_lado: int = MAX_LADO) -> Image.Image:
    img = img.convert("RGB")
    if max(img.size) > max_lado:
        f = max_lado / max(img.size)
        img = img.resize((max(1, round(img.width * f)), max(1, round(img.height * f))), Image.LANCZOS)
    return img


def normalizar(img: Image.Image) -> np.ndarray:
    x = np.asarray(img, dtype=np.float32) / 255.0
    return ((x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32))


def mosaico(img: Image.Image, lado: int, paso: int):
    """Pedazos lado x lado (CHW normalizados) y su posición. Si la foto es más chica que `lado`, se rellena
    con negro (igual al entrenar y al analizar)."""
    w, h = img.size
    W, H = max(w, lado), max(h, lado)
    x = np.zeros((H, W, 3), np.float32)
    x[:] = normalizar(Image.new("RGB", (1, 1)))[0, 0]          # negro normalizado
    x[:h, :w] = normalizar(img)
    tiles, pos = [], []
    for yy in posiciones(H, lado, paso):
        for xx in posiciones(W, lado, paso):
            tiles.append(x[yy:yy + lado, xx:xx + lado].transpose(2, 0, 1))
            pos.append((xx, yy))
    return np.stack(tiles).astype(np.float32), pos, (w, h), (W, H)


def puntuar_mosaico(correr, img: Image.Image, lado: int, paso: int, lote: int = 8):
    """`correr(lote_np) -> (mapas N x1xh xw, puntajes N)`. Devuelve (puntaje de la foto, mapa de la foto
    a 1/escala, escala). Puntaje = el del pedazo más sospechoso."""
    tiles, pos, (w, h), (W, H) = mosaico(img, lado, paso)
    mapas, puntajes = [], []
    for i in range(0, len(tiles), lote):
        m, s = correr(tiles[i:i + lote])
        mapas.append(np.asarray(m)); puntajes.append(np.asarray(s).reshape(-1))
    mapas, puntajes = np.concatenate(mapas)[:, 0], np.concatenate(puntajes)
    esc = lado // mapas.shape[-1]
    acc = np.zeros((H // esc + 1, W // esc + 1), np.float32)
    cnt = np.zeros_like(acc)
    for (xx, yy), m in zip(pos, mapas):
        acc[yy // esc:yy // esc + m.shape[0], xx // esc:xx // esc + m.shape[1]] += m
        cnt[yy // esc:yy // esc + m.shape[0], xx // esc:xx // esc + m.shape[1]] += 1
    mapa = (acc / np.maximum(cnt, 1))[:max(1, h // esc), :max(1, w // esc)]
    return float(puntajes.max()), mapa, esc


def degradar_fijo(img: Image.Image) -> Image.Image:
    """Lo mismo que el banco de pruebas: lado mayor 1600, JPEG 70 (para validar siempre igual)."""
    img = img.convert("RGB")
    img.thumbnail((1600, 1600), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


class Recortes:
    """Dataset de entrenamiento en recortes lado x lado a tamaño real (sin achicar la foto entera).
    En las editadas, la mayoría de los recortes caen sobre la zona cambiada. La etiqueta es del RECORTE:
    1 si contiene parte de la zona editada."""

    def __init__(self, filas: list[dict], lado: int = 512, semilla: int = 0, sobre_zona: float = .6):
        self.filas, self.lado, self.semilla, self.sobre_zona = filas, lado, semilla, sobre_zona
        self.epoca = 0

    def __len__(self):
        return len(self.filas)

    def __getitem__(self, i):
        f, L = self.filas[i], self.lado
        rng = random.Random(hash((self.semilla, self.epoca, i)))
        img = Image.open(f["ruta"]).convert("RGB")
        if f["mascara"]:
            mask = Image.open(f["mascara"]).convert("L").resize(img.size, Image.NEAREST)
        else:
            mask = Image.new("L", img.size, 255 if f["etiqueta"] else 0)
        img, mask = como_whatsapp(img, mask, rng)
        if max(img.size) > MAX_LADO:                         # como_whatsapp ya deja <= 2048; por si acaso
            img = preparar(img)
            mask = mask.resize(img.size, Image.NEAREST)
        if rng.random() < .5:
            img, mask = img.transpose(Image.FLIP_LEFT_RIGHT), mask.transpose(Image.FLIP_LEFT_RIGHT)
        w, h = img.size
        m = np.asarray(mask) > 127
        if f["etiqueta"] and m.any() and not m.all() and rng.random() < self.sobre_zona:
            ys, xs = np.nonzero(m)
            k = rng.randrange(len(xs))
            cx, cy = xs[k] + rng.randint(-L // 4, L // 4), ys[k] + rng.randint(-L // 4, L // 4)
            x0, y0 = cx - L // 2, cy - L // 2
        else:
            x0, y0 = rng.randint(0, max(0, w - L)), rng.randint(0, max(0, h - L))
        x0, y0 = min(max(0, x0), max(0, w - L)), min(max(0, y0), max(0, h - L))
        tiles, _, _, _ = mosaico(img.crop((x0, y0, min(w, x0 + L), min(h, y0 + L))), L, L)
        mm = np.zeros((L, L), np.float32)
        mc = m[y0:y0 + L, x0:x0 + L]
        mm[:mc.shape[0], :mc.shape[1]] = mc
        return tiles[0], mm[None], np.float32(mm.mean() > .001)


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
