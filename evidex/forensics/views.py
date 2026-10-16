"""Comparar dos fotos del mismo vehículo para encontrar una zona que no se ve igual en las dos.

Sirve para dos casos:
  misma toma    la foto original y su versión editada (con el mismo encuadre, recortada, girada o achicada).
  otra toma     dos fotos sacadas desde casi el mismo lugar, una después de la otra. Si a una se le agrandó,
                agregó o borró daño con IA (Galaxy AI, borrador mágico), esa zona deja de calzar con la otra.

Cómo: se buscan puntos característicos (SIFT, OpenCV, licencia Apache 2.0) en las dos fotos, se calcula la
transformación que lleva una sobre la otra (homografía con RANSAC) y se comparan zona por zona, con el brillo y
el contraste igualados localmente (para no confundir cambios de luz con cambios de contenido). Solo se informa
una diferencia donde el resto de la foto calza bien, y nunca fuera de la parte que muestran ambas fotos.

Una foto de otra toma tiene paralaje (lo que está más cerca se mueve más que el fondo), así que para «otra toma»
se exige que las fotos calcen muy bien en general y que la diferencia sea mucho mayor que el ruido del par.
Es una pista para que el analista compare, no una prueba: la alerta muestra la zona en las dos fotos.

Sin OpenCV (no instalado) la comparación no se hace y Evidex sigue igual.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

SIDE = 1024
MIN_GOOD = 40                 # parejas de puntos mínimas para intentar alinear
SAME = {"ratio": 0.9, "inliers": 150, "err": 1.6}       # calza casi perfecto: misma toma
OTHER = {"ratio": 0.45, "inliers": 80, "cover": 0.35}   # otra toma desde casi el mismo lugar
FLOOR = {"misma_toma": 0.6, "otra_toma": 0.95}          # diferencia mínima (en desviaciones locales)
NOISE_K = {"misma_toma": 2.5, "otra_toma": 3.5}         # veces el ruido normal del par
MIN_AREA = {"misma_toma": 0.0008, "otra_toma": 0.004}   # parte mínima de la zona común
MAX_ZONES = 3
SHIFT = {"misma_toma": 2, "otra_toma": 6}               # píxeles de desajuste tolerados (en 1024 px)
MARK_STRIP = 0.08             # franja inferior donde Samsung y Google estampan «Contenido generado por IA»


def available() -> bool:
    try:
        import cv2  # noqa: F401
        return True
    except Exception:
        return False


def _load(path: str) -> np.ndarray:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("L")
        s = SIDE / max(im.size)
        if s < 1:
            im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.Resampling.LANCZOS)
        return np.asarray(im)


@lru_cache(maxsize=48)
def _features(path: str, mtime: float):
    import cv2
    g = _load(path)
    sift = cv2.SIFT_create(nfeatures=4000)
    kp, des = sift.detectAndCompute(g, None)
    pts = np.float32([k.pt for k in kp]) if kp else np.zeros((0, 2), np.float32)
    return g, pts, des


def features(path) -> tuple:
    p = str(path)
    return _features(p, Path(p).stat().st_mtime)


def _norm(a: np.ndarray, sigma: float = 21) -> np.ndarray:
    import cv2
    a = a.astype(np.float32)
    m = cv2.GaussianBlur(a, (0, 0), sigma)
    v = cv2.GaussianBlur(a * a, (0, 0), sigma) - m * m
    return (a - m) / np.sqrt(np.maximum(v, 100))       # zonas lisas (cielo, techo): no amplificar el ruido


def _box_norm(x, y, w, h, W, H) -> list[float]:
    return [round(x / W, 4), round(y / H, 4), round((x + w) / W, 4), round((y + h) / H, 4)]


def compare(path_a, path_b, ignore_marks: bool = False) -> dict | None:
    """Alinea b sobre a. Devuelve None si no muestran lo mismo; si no:
    {"kind": "misma_toma"|"otra_toma", "inliers", "ratio", "err", "cover", "noise",
     "zones": [{"box": [x0,y0,x1,y1] en a, "box_b": en b, "where", "strength", "area"}]}."""
    import cv2
    from evidex.forensics.derived import where
    A, pa, da = features(path_a)
    Bm, pb, db = features(path_b)
    if da is None or db is None or len(pa) < MIN_GOOD or len(pb) < MIN_GOOD:
        return None
    matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=4), dict(checks=48))
    try:
        pairs = matcher.knnMatch(db, da, k=2)
    except cv2.error:
        return None
    good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < MIN_GOOD:
        return None
    src = np.float32([pb[g.queryIdx] for g in good])
    dst = np.float32([pa[g.trainIdx] for g in good])
    H, inl = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    if H is None:
        return None
    inl = inl.ravel().astype(bool)
    n_in, ratio = int(inl.sum()), float(inl.mean())
    if n_in < 4:
        return None
    proj = cv2.perspectiveTransform(src[inl].reshape(-1, 1, 2), H).reshape(-1, 2)
    err = float(np.median(np.linalg.norm(proj - dst[inl], axis=1))) if n_in else 99.0
    h, w = A.shape
    valid = cv2.warpPerspective(np.full(Bm.shape, 255, np.uint8), H, (w, h))
    valid = cv2.erode(valid, np.ones((25, 25), np.uint8)) > 0
    hull = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(hull, cv2.convexHull(dst[inl].astype(np.int32)), 255)
    region = valid & (cv2.dilate(hull, np.ones((61, 61), np.uint8)) > 0)
    cover = float(region.mean())
    # misma toma: calza casi todo, o calza perfecto lo que no cambió (una edición grande deja muchos puntos sin pareja)
    if n_in >= SAME["inliers"] and (ratio >= SAME["ratio"] and err <= SAME["err"] or ratio >= 0.5 and err <= 0.8):
        kind = "misma_toma"
    elif ratio >= OTHER["ratio"] and n_in >= OTHER["inliers"] and cover >= OTHER["cover"]:
        kind = "otra_toma"
    else:
        return None
    if kind == "misma_toma":            # misma toma: la alineación vale para toda la foto, no solo donde hubo puntos
        region = valid
    Bw = cv2.warpPerspective(Bm, H, (w, h))
    inside = cv2.warpPerspective(np.full(Bm.shape, 255, np.uint8), H, (w, h)) > 0
    Bw[~inside] = A[~inside]            # fuera de la otra foto: igual a esta, para que el borde no cuente como cambio
    na = _norm(cv2.GaussianBlur(A, (0, 0), 1.5))
    nb = _norm(cv2.GaussianBlur(Bw, (0, 0), 1.5))
    # diferencia que tolera un desajuste de pocos píxeles (giro, paralaje, interpolación): un cambio real de
    # contenido sigue distinto aunque se corra la imagen; un borde mal alineado, no
    r = SHIFT[kind]
    d = None
    for dy in range(-r, r + 1, max(1, r // 2)):
        for dx in range(-r, r + 1, max(1, r // 2)):
            m = cv2.GaussianBlur(np.abs(na - np.roll(nb, (dy, dx), (0, 1))), (0, 0), 4)
            d = m if d is None else np.minimum(d, m)
    d = cv2.GaussianBlur(d, (0, 0), 3)
    d[~region] = 0
    vals = d[region]
    med = float(np.median(vals)) if vals.size else 0.0
    mad = float(np.median(np.abs(vals - med))) * 1.4826 if vals.size else 0.0
    noise = float(np.percentile(vals, 99)) if vals.size else 0.0
    thr = max(FLOOR[kind], med + NOISE_K[kind] * mad)
    if kind == "misma_toma":            # una edición muy grande infla la estadística; en la misma toma el ruido es bajo
        thr = min(thr, 0.9)
    hot = cv2.morphologyEx((d > thr).astype(np.uint8), cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    hot = cv2.morphologyEx(hot, cv2.MORPH_CLOSE, np.ones((31, 31), np.uint8))   # une trozos de una misma zona
    strip = np.zeros((h, w), bool)
    if ignore_marks:                    # la marca de IA estampada abajo es una diferencia esperada, no un cambio
        strip[int(h * (1 - MARK_STRIP)):, :] = True
        hb, wb = Bm.shape
        sb = np.zeros((hb, wb), np.uint8)
        sb[int(hb * (1 - MARK_STRIP)):, :] = 255
        strip |= cv2.warpPerspective(sb, H, (w, h)) > 0
    n, lab, st, _ = cv2.connectedComponentsWithStats(hot)
    area_all = max(1, int(region.sum()))
    Hinv = np.linalg.inv(H)
    hb, wb = Bm.shape
    zones = []
    for i in range(1, n):
        x, y, bw, bh, a = (int(v) for v in st[i])
        if a / area_all < MIN_AREA[kind]:
            continue
        comp = lab == i
        if strip[comp].mean() > 0.6:
            continue
        strength = float(d[comp].mean())
        if kind == "otra_toma" and strength < thr * 1.1:
            continue
        corners = np.float32([[x, y], [x + bw, y], [x + bw, y + bh], [x, y + bh]]).reshape(-1, 1, 2)
        cb = cv2.perspectiveTransform(corners, Hinv).reshape(-1, 2)
        bx0, by0 = np.clip(cb.min(0), 0, [wb, hb])
        bx1, by1 = np.clip(cb.max(0), 0, [wb, hb])
        box = _box_norm(x, y, bw, bh, w, h)
        zones.append({"box": box, "box_b": [round(float(bx0) / wb, 4), round(float(by0) / hb, 4),
                                            round(float(bx1) / wb, 4), round(float(by1) / hb, 4)],
                      "where": where(box), "strength": round(strength, 2), "area": round(a / area_all, 4)})
    zones.sort(key=lambda z: -z["strength"] * z["area"] ** 0.5)
    return {"kind": kind, "inliers": n_in, "ratio": round(ratio, 3), "err": round(err, 2), "cover": round(cover, 3),
            "noise": round(noise, 3), "thr": round(thr, 3), "zones": zones[:MAX_ZONES]}


def side_by_side(path_a, path_b, zones: list[dict], height: int = 720) -> bytes:
    """Las dos fotos lado a lado con las zonas distintas marcadas en ambas (PNG)."""
    from PIL import ImageDraw
    import io
    ims = []
    for path, key in ((path_a, "box"), (path_b, "box_b")):
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            s = height / im.height
            im = im.resize((max(1, round(im.width * s)), height), Image.Resampling.LANCZOS)
        dr = ImageDraw.Draw(im)
        for n, z in enumerate(zones, 1):
            x0, y0, x1, y1 = z[key]
            pad = 6
            box = [max(2, x0 * im.width - pad), max(24, y0 * im.height - pad),
                   min(im.width - 3, x1 * im.width + pad), min(im.height - 3, y1 * im.height + pad)]
            dr.rectangle(box, outline=(225, 29, 72), width=4)
            dr.rectangle([box[0], box[1] - 22, box[0] + 22, box[1]], fill=(225, 29, 72))
            dr.text((box[0] + 7, box[1] - 19), str(n), fill="white")
        ims.append(im)
    gap = 16
    out = Image.new("RGB", (ims[0].width + ims[1].width + gap, height), "white")
    out.paste(ims[0], (0, 0))
    out.paste(ims[1], (ims[0].width + gap, 0))
    b = io.BytesIO()
    out.save(b, "PNG", optimize=True)
    return b.getvalue()
