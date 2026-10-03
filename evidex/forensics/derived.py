"""Fotos derivadas de otra: recortes y marcas visibles de IA.

Recorte: una foto del caso puede ser otra foto del mismo caso recortada (y reenviada, por ejemplo por
WhatsApp, que cambia el tamaño). Se busca la foto chica dentro de la grande a varias escalas con
correlación normalizada (sin rotación). Si calza casi perfecto, es un recorte, y se sabe qué bordes se
quitaron. Eso importa cuando la foto completa tiene algo que la recortada ya no muestra: la marca
"Contenido generado por IA" que ponen Samsung, Google y otras apps en la esquina, una fecha impresa,
otra patente.

Marca visible de IA: texto como "Contenido generado por IA" o "AI-generated" leído por el OCR en la
propia imagen.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import numpy as np
from PIL import Image

COARSE_SIDE, FINE_SIDE = 96, 256
MATCH = 0.93          # correlación mínima para decir "es la misma imagen"
MIN_COVER, SAME_COVER = 0.25, 0.97   # parte de la foto grande que muestra la chica

# textos que las apps estampan en imágenes hechas o editadas con IA (se comparan sin tildes ni mayúsculas)
AI_LABELS = [
    r"generad[oa]s? (por|con) (la )?ia", r"cread[oa]s? (por|con) (la )?ia", r"editad[oa]s? (por|con) (la )?ia",
    r"contenido generado", r"hech[oa] con (la )?ia", r"imagen (generada|creada) (por|con)",
    r"ai[- ]?generated", r"generated (by|with) ai", r"made with ai", r"edited with ai", r"created with ai",
    r"imagined with", r"ai[- ]?edited", r"gerad[oa] (por|com) ia", r"\bmeta ai\b", r"\bgalaxy ai\b",
]
_AI_RE = re.compile("|".join(AI_LABELS))


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s)


def ai_label(ocr_text: str) -> str | None:
    """El texto de marca de IA leído en la imagen, o None."""
    for part in (ocr_text or "").split("|"):
        if _AI_RE.search(_plain(part)):
            return part.strip()
    return None


# ---- recortes ---------------------------------------------------------------
@lru_cache(maxsize=64)
def _gray_cached(path: str, mtime: float, side: int) -> np.ndarray:
    with Image.open(path) as im:
        im = im.convert("L")
        s = side / max(im.size)
        im = im.resize((max(8, round(im.width * s)), max(8, round(im.height * s))), Image.Resampling.BILINEAR)
        return np.asarray(im, np.float64)


def _gray(path, side: int) -> np.ndarray:
    from pathlib import Path
    p = Path(path)
    return _gray_cached(str(p), p.stat().st_mtime, side)


def _resize(a: np.ndarray, w: int, h: int) -> np.ndarray:
    return np.asarray(Image.fromarray(a.astype(np.float32), "F").resize((w, h), Image.Resampling.BILINEAR), np.float64)


def _ncc(big: np.ndarray, tpl: np.ndarray) -> tuple[float, int, int]:
    """Mejor correlación normalizada de tpl dentro de big y su posición (x, y)."""
    H, W = big.shape
    h, w = tpl.shape
    if h > H or w > W:
        return -1.0, 0, 0
    t = tpl - tpl.mean()
    tn = np.sqrt((t ** 2).sum())
    if tn < 1e-6:
        return -1.0, 0, 0
    shape = (H + h, W + w)
    F = np.fft.rfft2(big, shape)
    num = np.fft.irfft2(F * np.conj(np.fft.rfft2(t, shape)), shape)[:H - h + 1, :W - w + 1]
    # suma y suma de cuadrados de cada ventana con imágenes integrales
    def win(a):
        c = np.pad(a, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
        return c[h:, w:] - c[:-h, w:] - c[h:, :-w] + c[:-h, :-w]
    s1, s2 = win(big), win(big ** 2)
    var = np.maximum(s2 - s1 ** 2 / (h * w), 1e-6)
    r = num / (np.sqrt(var) * tn)
    y, x = np.unravel_index(int(np.argmax(r)), r.shape)
    return float(r[y, x]), int(x), int(y)


def _search(big: np.ndarray, small: np.ndarray, scales) -> tuple[float, float, int, int]:
    best = (-1.0, 0.0, 0, 0)
    H, W = big.shape
    for k in scales:
        w, h = round(small.shape[1] * k), round(small.shape[0] * k)
        if w < 16 or h < 16 or w > W or h > H:
            continue
        r, x, y = _ncc(big, _resize(small, w, h))
        if r > best[0]:
            best = (r, k, x, y)
    return best


def crop_of(big_path, small_path) -> dict | None:
    """Si la foto small es un recorte de la foto big, devuelve qué parte de big muestra; si no, None."""
    big_c, small_c = _gray(big_path, COARSE_SIDE), _gray(small_path, COARSE_SIDE)
    # la foto chica, llevada a la escala de la grande: su ancho ocupa entre 25% y 100% del de la grande
    kmax = min(big_c.shape[1] / small_c.shape[1], big_c.shape[0] / small_c.shape[0])
    r, k, _, _ = _search(big_c, small_c, np.linspace(kmax * 0.45, kmax, 22))
    if r < MATCH - 0.08:
        return None
    big, small = _gray(big_path, FINE_SIDE), _gray(small_path, FINE_SIDE)
    f = FINE_SIDE / COARSE_SIDE * small_c.shape[1] / small.shape[1]
    r, k, x, y = _search(big, small, np.linspace(k * f * 0.96, min(k * f * 1.04, min(
        big.shape[1] / small.shape[1], big.shape[0] / small.shape[0])), 17))
    if r < MATCH:
        return None
    H, W = big.shape
    w, h = small.shape[1] * k, small.shape[0] * k
    cover = (w * h) / (W * H)
    if cover < MIN_COVER:
        return None
    cut = {"izquierda": x / W, "arriba": y / H, "derecha": max(0.0, (W - x - w) / W), "abajo": max(0.0, (H - y - h) / H)}
    cut = {s: round(float(v), 3) for s, v in cut.items() if v >= 0.02}
    return {"score": round(float(r), 3), "cover": round(float(cover), 3), "same": cover >= SAME_COVER or not cut,
            "box": [round(float(v), 3) for v in (x / W, y / H, (x + w) / W, (y + h) / H)], "cut": cut}


def crop_relation(path_a, path_b) -> dict | None:
    """Relación entre dos fotos: {"base": "a"|"b", ...crop_of} si una es recorte de la otra."""
    try:
        with Image.open(path_a) as a, Image.open(path_b) as b:
            area_a, area_b = a.width * a.height, b.width * b.height
            ra, rb = a.width / a.height, b.width / b.height
    except Exception:
        return None
    # se busca primero la de menos "campo" dentro de la otra; si no calza, al revés
    order = [("a", path_a, path_b), ("b", path_b, path_a)]
    if abs(ra - rb) < 0.01:
        order.sort(key=lambda o: -(area_a if o[0] == "a" else area_b))
    for base, big, small in order:
        try:
            rel = crop_of(big, small)
        except Exception:
            rel = None
        if rel and not rel["same"]:
            return {"base": base, **rel}
    return None


# ---- proporción ---------------------------------------------------------------
CAMERA_RATIOS = [4 / 3, 16 / 9, 1.0, 3 / 2, 5 / 4, 2.0, 18 / 9, 19.5 / 9, 20 / 9, 21 / 9, 65 / 24]


def odd_ratio(w: int, h: int) -> float | None:
    """Proporción que no sale de ninguna cámara ni pantalla (foto recortada a mano o generada)."""
    if not w or not h:
        return None
    r = max(w, h) / min(w, h)
    if any(abs(r - c) / c < 0.015 for c in CAMERA_RATIOS):
        return None
    return round(r, 3)
