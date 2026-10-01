"""Análisis del contenido de la imagen (los píxeles), útil aunque la foto no traiga metadatos.

  1. Doble compresión JPEG ("JPEG ghost", Farid 2009): una foto guardada dos veces conserva
     una huella de su primera calidad. Si además una zona no tiene esa huella, esa zona se
     agregó después (posible pegado de daño, patente u objeto).
  2. Clonado dentro de la misma foto (copy-move): una parte de la imagen copiada en otro lugar,
     por ejemplo para agrandar un daño o tapar algo.
  3. Luz contra hora: cielo de día en una foto que dice haberse tomado de noche.
  4. Credenciales de contenido C2PA (Pixel 10/11 y otras cámaras firman sus fotos): si la firma
     existe y es válida, la foto no se modificó desde la cámara; si es inválida, sí.

Calibrado con fotos reales de muestra: con fotos limpias no aparecieron zonas ni clonados;
con falsificaciones de prueba se detectó la mayoría, no todas. Una edición cuidadosa (por
ejemplo, guardar a la misma calidad, o retocar con IA generativa) puede no dejar huellas.
"""
from __future__ import annotations

import io
import math
from collections import deque
from datetime import datetime, timedelta

import numpy as np
from PIL import Image, ImageDraw

STD_LUMA = np.array([16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56,
                     14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
                     49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99], dtype=np.float64)
GHOST_DEPTH = 0.055        # profundidad mínima del "fantasma" de la primera compresión
REGION_FRAC, REGION_Z = 0.04, 15.0
CLONE_MIN = 40             # coincidencias mínimas con el mismo desplazamiento
BLOCK = 16


# ---- utilidades -------------------------------------------------------------------------
def _jpeg(img: Image.Image, q: int) -> Image.Image:
    b = io.BytesIO()
    img.save(b, "JPEG", quality=q)
    b.seek(0)
    return Image.open(b).convert("L")


def _gray(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"), dtype=np.float32)


def _bmean(a: np.ndarray, b: int = BLOCK) -> np.ndarray:
    h, w = a.shape[0] // b * b, a.shape[1] // b * b
    return a[:h, :w].reshape(h // b, b, w // b, b).mean(axis=(1, 3))


def _largest_blob(mask: np.ndarray) -> np.ndarray:
    """Mayor región conectada (4-vecinos) de una máscara pequeña de bloques."""
    seen = np.zeros_like(mask, dtype=bool)
    best: list = []
    h, w = mask.shape
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        comp, dq = [], deque([(y, x)])
        seen[y, x] = True
        while dq:
            cy, cx = dq.popleft()
            comp.append((cy, cx))
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    dq.append((ny, nx))
        if len(comp) > len(best):
            best = comp
    out = np.zeros_like(mask, dtype=bool)
    for y, x in best:
        out[y, x] = True
    return out


def estimate_quality(img: Image.Image) -> int | None:
    """Calidad JPEG aproximada (escala de libjpeg) a partir de la tabla de cuantización."""
    tables = getattr(img, "quantization", None) or {}
    if 0 not in tables:
        return None
    target = float(np.sum(tables[0]))
    best, err = None, 1e18
    for q in range(1, 101):
        scale = 5000 / q if q < 50 else 200 - 2 * q
        t = np.clip(np.floor((STD_LUMA * scale + 50) / 100), 1, 255)
        e = abs(t.sum() - target)
        if e < err:
            best, err = q, e
    return best


# ---- 1. doble compresión y zonas pegadas ------------------------------------------------
def ghost(img: Image.Image, q_final: int | None) -> dict:
    """Busca la calidad de una compresión anterior y zonas que no la comparten."""
    if q_final is None:
        return {}
    # la curva se calcula en cuatro recortes: si una zona se pegó, los otros conservan la huella
    w, h = img.size
    s = min(768, w // 2 // 8 * 8, h // 2 // 8 * 8)
    if s < 128:
        s = min(w, h) // 8 * 8
        corners = [(0, 0)]
    else:
        corners = [(x, y) for x in (0, (w - s) // 8 * 8) for y in (0, (h - s) // 8 * 8)]
        corners.append(((w - s) // 2 // 8 * 8, (h - s) // 2 // 8 * 8))
    qs = list(range(40, 100, 2))
    first, depth = None, 0.0
    rgb = img.convert("RGB")
    for x0, y0 in corners:
        crop = rgb.crop((x0, y0, x0 + s, y0 + s))
        a = _gray(crop)
        t = s // 16 * 16
        tx = float((a[:t, :t].reshape(t // 16, 16, t // 16, 16).std(axis=(1, 3)) > 4).mean())
        if tx < 0.3:   # recorte casi liso (cielo, pared, dibujo): su curva no es confiable
            continue
        d = np.array([float(((a - _gray(_jpeg(crop, q))) ** 2).mean()) for q in qs])
        d = d / (d.max() + 1e-9)
        for i in range(1, len(d) - 1):
            if d[i] < d[i - 1] and d[i] < d[i + 1] and qs[i] < q_final - 6:
                lo, hi = max(0, i - 3), min(len(d) - 1, i + 3)
                dep = (d[lo] + d[hi]) / 2 - d[i]
                if dep > depth:
                    first, depth = qs[i], dep
    out = {"q_final": q_final}
    # en imágenes casi lisas (dibujos, gráficos) la curva tiene mínimos espurios: no se concluye nada
    if first is None or depth < GHOST_DEPTH:
        return out
    out.update(q_first=int(first), depth=round(float(depth), 3))

    # zonas sin la huella de la primera compresión (en la imagen completa, reducida si es enorme)
    full = img.convert("RGB")
    if max(full.size) > 3000:  # mantener la grilla de 8 px: recortar en vez de reducir
        cw, ch = min(full.width, 3000) // 8 * 8, min(full.height, 3000) // 8 * 8
        ox, oy = (full.width - cw) // 2 // 8 * 8, (full.height - ch) // 2 // 8 * 8
        full = full.crop((ox, oy, ox + cw, oy + ch))
    else:
        ox = oy = 0
    g = _gray(full)
    d1 = _bmean((g - _gray(_jpeg(full, first))) ** 2)
    d0 = _bmean((g - _gray(_jpeg(full, max(first - 15, 20)))) ** 2)
    lum = _bmean(g)
    tex = (d0 > 1.0) & (lum > 20) & (lum < 235)   # zonas quemadas o negras no guardan la huella
    if tex.sum() < 20:
        return out
    r = np.where(tex, d1 / (d0 + 1.0), np.nan)
    v = r[tex]
    med = np.median(v)
    mad = np.median(np.abs(v - med)) + 1e-6
    z = np.nan_to_num((r - med) / (1.4826 * mad), nan=0.0)
    blob = _largest_blob(z > 5)
    frac = blob.sum() / tex.sum()
    if blob.any() and frac >= REGION_FRAC and z[blob].mean() >= REGION_Z:
        ys, xs = np.nonzero(blob)
        out["region"] = {"frac": round(float(frac), 3), "z": round(float(z[blob].mean()), 1),
                         "bbox": [int(ox + xs.min() * BLOCK), int(oy + ys.min() * BLOCK),
                                  int(ox + (xs.max() + 1) * BLOCK), int(oy + (ys.max() + 1) * BLOCK)]}
    return out


# ---- 2. clonado dentro de la foto ----------------------------------------------------------
def _dct_matrix(n: int) -> np.ndarray:
    k = np.arange(n)[:, None]
    x = np.arange(n)[None, :]
    c = np.cos(np.pi * (2 * x + 1) * k / (2 * n)) * np.sqrt(2 / n)
    c[0] /= np.sqrt(2)
    return c


_C = _dct_matrix(BLOCK)


def copy_move(img: Image.Image, maxside: int = 360) -> dict:
    g = img.convert("L")
    s = maxside / max(g.size)
    if s < 1:
        g = g.resize((max(1, int(g.width * s)), max(1, int(g.height * s))), Image.Resampling.LANCZOS)
    else:
        s = 1.0
    a = np.asarray(g, dtype=np.float32)
    if min(a.shape) < BLOCK * 4:
        return {}
    win = np.lib.stride_tricks.sliding_window_view(a, (BLOCK, BLOCK))
    h, w = win.shape[:2]
    ys, xs = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    blocks = win.reshape(-1, BLOCK, BLOCK)
    # fuera zonas planas (cielo, pared) y bordes rectos (postes, aristas): coinciden sin ser copias
    gy = np.abs(np.diff(blocks, axis=1)).mean(axis=(1, 2))
    gx = np.abs(np.diff(blocks, axis=2)).mean(axis=(1, 2))
    keep = (blocks.std(axis=(1, 2)) > 6) & (np.minimum(gx, gy) > 0.35 * np.maximum(gx, gy)) & (np.minimum(gx, gy) > 1.0)
    blocks, ys, xs = blocks[keep], ys.ravel()[keep], xs.ravel()[keep]
    if len(blocks) < 100:
        return {}
    d = _C @ blocks @ _C.T
    feat = np.stack([d[:, 0, 0] / 8, d[:, 0, 1] / 4, d[:, 1, 0] / 4, d[:, 1, 1] / 3, d[:, 0, 2] / 3,
                     d[:, 2, 0] / 3, d[:, 2, 2] / 2, d[:, 1, 2] / 2, d[:, 2, 1] / 2], 1)
    order = np.lexsort(np.round(feat / 4.0).T[::-1])
    feat, ys, xs = feat[order], ys[order], xs[order]
    pairs: dict[tuple[int, int], list] = {}
    for off in range(1, 8):
        i = np.nonzero(np.linalg.norm(feat[off:] - feat[:-off], axis=1) < 2.5)[0]
        dy, dx = ys[i + off] - ys[i], xs[i + off] - xs[i]
        sign = np.where((dy < 0) | ((dy == 0) & (dx < 0)), -1, 1)
        dy, dx = dy * sign, dx * sign
        far = dy * dy + dx * dx >= (3 * BLOCK) ** 2
        src_y = np.where(sign > 0, ys[i], ys[i + off])
        src_x = np.where(sign > 0, xs[i], xs[i + off])
        for k in np.nonzero(far)[0]:
            pairs.setdefault((int(dy[k]), int(dx[k])), []).append((int(src_y[k]), int(src_x[k])))
    if not pairs:
        return {}
    # agrupar desplazamientos casi iguales (±2 px) y quedarse con el más repetido
    best_key = max(pairs, key=lambda k: sum(len(v) for kk, v in pairs.items()
                                            if abs(kk[0] - k[0]) <= 2 and abs(kk[1] - k[1]) <= 2))
    pts = [p for kk, v in pairs.items() if abs(kk[0] - best_key[0]) <= 2 and abs(kk[1] - best_key[1]) <= 2 for p in v]
    if len(pts) < CLONE_MIN:
        return {"matches": len(pts)}
    py = np.array([p[0] for p in pts])
    px = np.array([p[1] for p in pts])
    inv = 1 / s
    src = [int(px.min() * inv), int(py.min() * inv), int((px.max() + BLOCK) * inv), int((py.max() + BLOCK) * inv)]
    dy, dx = best_key[0] * inv, best_key[1] * inv
    dst = [int(src[0] + dx), int(src[1] + dy), int(src[2] + dx), int(src[3] + dy)]
    return {"matches": len(pts), "src": src, "dst": dst}


# ---- 3. luz contra hora ------------------------------------------------------------------------
def chile_offset(dt: datetime) -> timedelta:
    """Diferencia con UTC en Chile continental (horario de verano aprox. septiembre a abril)."""
    try:
        from zoneinfo import ZoneInfo
        off = dt.replace(tzinfo=ZoneInfo("America/Santiago")).utcoffset()
        if off is not None:
            return off
    except Exception:  # Windows sin base de zonas horarias
        pass
    return timedelta(hours=-3) if (dt.month >= 9 or dt.month <= 3) else timedelta(hours=-4)


def solar_elevation(lat: float, lon: float, when_utc: datetime) -> float:
    """Altura del sol en grados (aproximación NOAA, error menor a 1°)."""
    doy = when_utc.timetuple().tm_yday
    hour = when_utc.hour + when_utc.minute / 60 + when_utc.second / 3600
    g = 2 * math.pi / 365 * (doy - 1 + (hour - 12) / 24)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    tst = hour * 60 + eqt + 4 * lon
    ha = math.radians(tst / 4 - 180)
    la = math.radians(lat)
    cosz = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    return 90 - math.degrees(math.acos(max(-1.0, min(1.0, cosz))))


def daylight_sky(img: Image.Image) -> bool:
    """Franja superior clara y azulada: cielo de día (un flash no ilumina el cielo)."""
    small = img.convert("RGB").resize((96, 96))
    a = np.asarray(small, dtype=np.float32)[:24] / 255
    lum = a.mean()
    blue = (a[..., 2] - a[..., 0]).mean()
    return bool(lum > 0.55 and blue > 0.03)


# ---- 4. C2PA ---------------------------------------------------------------------------------------
def c2pa_status(path) -> dict | None:
    """None si no hay credenciales o falta la librería; si no, {'valid': bool, 'generator': str}."""
    raw = open(path, "rb").read(6_000_000)
    if b"c2pa" not in raw and b"jumb" not in raw:
        return None
    try:
        import c2pa  # pip install c2pa-python (opcional)
    except ImportError:
        return {"valid": None, "generator": "", "note": "tiene credenciales C2PA; instale c2pa-python para validarlas"}
    try:
        with c2pa.Reader(str(path)) as r:
            state = (r.get_validation_state() or "").lower()
            info = r.json()
        gen = ""
        try:
            import json as _j
            m = _j.loads(info)
            act = m.get("manifests", {}).get(m.get("active_manifest", ""), {})
            gen = (act.get("claim_generator_info") or [{}])[0].get("name", "") or act.get("claim_generator", "")
        except Exception:
            pass
        return {"valid": state in ("valid", "trusted"), "state": state, "generator": gen}
    except Exception as ex:
        return {"valid": False, "state": type(ex).__name__, "generator": ""}


# ---- conjunto ------------------------------------------------------------------------------------------
def analyze_image(path) -> dict:
    with Image.open(path) as img:
        img.load()
        q = estimate_quality(img) if img.format == "JPEG" else None
        out = {"ghost": ghost(img, q) if q else {}, "clone": copy_move(img), "sky_day": daylight_sky(img)}
    c = c2pa_status(path)
    if c is not None:
        out["c2pa"] = c
    return out


def overlay(path, content: dict, maxside: int = 900) -> bytes | None:
    """Imagen reducida con las zonas sospechosas marcadas (PNG), para mostrar al liquidador."""
    boxes = []
    if (content.get("ghost") or {}).get("region"):
        boxes.append((content["ghost"]["region"]["bbox"], (220, 38, 38), "zona agregada"))
    cl = content.get("clone") or {}
    if cl.get("src"):
        boxes += [(cl["src"], (234, 140, 0), "original"), (cl["dst"], (234, 140, 0), "copia")]
    if not boxes:
        return None
    with Image.open(path) as img:
        im = img.convert("RGB")
    s = min(1.0, maxside / max(im.size))
    im = im.resize((int(im.width * s), int(im.height * s)))
    dr = ImageDraw.Draw(im)
    for (x0, y0, x1, y1), col, label in boxes:
        box = [x0 * s, y0 * s, x1 * s, y1 * s]
        dr.rectangle(box, outline=col, width=4)
        dr.rectangle([box[0], box[1] - 18, box[0] + 8 * len(label) + 8, box[1]], fill=col)
        dr.text((box[0] + 4, box[1] - 16), label, fill=(255, 255, 255))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()
