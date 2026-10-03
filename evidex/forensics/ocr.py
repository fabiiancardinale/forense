"""Lectura de texto en imágenes (OCR): documentos escaneados y patentes en las fotos.

Usa RapidOCR (pip install rapidocr_onnxruntime), que funciona sin instalar programas aparte y
sin internet. Es opcional: si no está instalado, Evidex sigue funcionando sin OCR.

  - PDF escaneados (sin texto digital): se renderiza cada página y se lee su texto, para que
    las revisiones de RUT, patentes y fechas funcionen también con documentos en papel.
  - Fotos del vehículo: se busca una patente chilena legible y se compara con la declarada.

Límites: la lectura depende de la nitidez; una patente lejana, sucia o en ángulo puede no
leerse. El modelo está entrenado en inglés y chino, así que puede perder tildes y eñes; los
números, RUT, fechas y patentes se leen bien.
"""
from __future__ import annotations

import io
import re

from PIL import Image

from evidex.forensics.chile import plate_format, plates_in

_engine = None
MAX_SIDE = 1800
MAX_PAGES = 5


def available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


def _get():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def read_image(img: Image.Image) -> list[tuple[str, float]]:
    """Líneas leídas con su confianza (0 a 1)."""
    import numpy as np
    im = img.convert("RGB")
    s = MAX_SIDE / max(im.size)
    if s < 1:
        im = im.resize((int(im.width * s), int(im.height * s)))
    res, _ = _get()(np.asarray(im)[:, :, ::-1])      # BGR, como espera el motor
    return [(r[1], float(r[2])) for r in (res or [])]


def pdf_text(raw: bytes) -> str:
    """Texto de un PDF escaneado, página por página."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(io.BytesIO(raw))
    out = []
    try:
        for i in range(min(len(pdf), MAX_PAGES)):
            img = pdf[i].render(scale=2).to_pil()
            out.append("\n".join(t for t, _ in read_image(img)))
    finally:
        pdf.close()
    return "\n".join(out)


def plates(lines: list[tuple[str, float]]) -> list[str]:
    """Patentes chilenas válidas en las líneas leídas (KX·TR45, KXTR-45, KXTR 45...)."""
    found = []
    for text, score in lines:
        if score < 0.6:
            continue
        compact = re.sub(r"[^A-Z0-9]", "", text.upper())
        cands = [compact] if 5 <= len(compact) <= 7 else plates_in(text)
        for c in cands:
            if plate_format(c) in ("nueva", "antigua") and c not in found and not _looks_like_text(c):
                found.append(c)
    return found


COMMON = {"DE", "EL", "LA", "LO", "AL", "EN", "LE", "SE", "UN", "NO", "SI", "YA", "MI", "TU", "SU", "ES", "AM", "PM",
          "NR", "NO", "TL", "CL", "RT", "ID", "SN", "DO"}


def _looks_like_text(p: str) -> bool:
    """Descarta lecturas que parecen texto y no patente: "de 2026", "al 1990" (años, palabras cortas)."""
    if plate_format(p) != "antigua":
        return False
    letters, digits = p[:2], int(p[2:])
    return letters in COMMON or 1950 <= digits <= 2039


def analyze_photo(path) -> dict:
    with Image.open(path) as img:
        lines = read_image(img)
    return {"plates": plates(lines), "text": " | ".join(t for t, s in lines if s >= 0.6)[:500]}
