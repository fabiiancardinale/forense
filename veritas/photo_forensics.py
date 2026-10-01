"""Señales de metadatos manipulados o de capturas de pantalla en una foto.

Cambiar la fecha de una foto es fácil (apps de edición de EXIF, ExifTool). Lo difícil es
cambiarla en todos los lugares donde queda escrita de forma coherente. Este módulo busca
esas incoherencias:

  1. Las tres fechas EXIF (original, digitalizada, modificación) no coinciden.
  2. La hora del GPS (que el teléfono escribe en UTC) no calza con la fecha de la foto.
  3. La miniatura que el teléfono guarda dentro del archivo muestra otra imagen.
  4. Hay marca y modelo de cámara, pero faltan los datos de exposición que toda cámara
     escribe (exposición, apertura, ISO): metadatos agregados a mano.
  5. Rastros de herramientas que reescriben metadatos (ExifTool, editores de EXIF).
  6. Fecha de la foto en el futuro respecto de su recepción.
  7. Captura de pantalla (marca explícita del sistema, nombre del archivo, o formato y
     tamaño de pantalla de celular sin datos de cámara).

Límites: una manipulación cuidadosa puede no dejar ninguna de estas huellas. Cada señal es
un motivo para revisar, no una prueba.
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timedelta

from PIL import Image

METADATA_TOOLS = {
    b"Image::ExifTool": "ExifTool", b"exiftool": "ExifTool", b"Photo Exif Editor": "Photo Exif Editor",
    b"Exif Editor": "un editor de EXIF", b"EXIF Eraser": "EXIF Eraser", b"Metapho": "Metapho",
    b"ExifPro": "ExifPro", b"piexif": "piexif", b"Photo Investigator": "Photo Investigator",
    b"xmpMM:History": "historial de edición XMP",
}
SCREENSHOT_NAME = re.compile(r"(screenshot|captura|pantallazo|screen[ _-]?shot|scr_\d)", re.I)
PHONE_WIDTHS = {720, 750, 828, 1080, 1125, 1170, 1179, 1242, 1284, 1290, 1440, 1320, 1206}

DATE_TOLERANCE = timedelta(minutes=1)
GPS_TOLERANCE = timedelta(minutes=10)
MAX_TZ = timedelta(hours=14)


def _date(v) -> datetime | None:
    try:
        return datetime.strptime(str(v).strip("\x00 "), "%Y:%m:%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def _offset(v) -> timedelta | None:
    m = re.fullmatch(r"([+-])(\d{2}):(\d{2})", str(v or "").strip("\x00 "))
    if not m:
        return None
    td = timedelta(hours=int(m[2]), minutes=int(m[3]))
    return td if m[1] == "+" else -td


def _gps_utc(gps: dict) -> datetime | None:
    try:
        d = datetime.strptime(str(gps[29]).strip("\x00 "), "%Y:%m:%d")
        h, mi, s = (float(x) for x in gps[7])
        return d + timedelta(hours=h, minutes=mi, seconds=s)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def _thumbnail(raw: bytes) -> Image.Image | None:
    """Miniatura JPEG dentro del bloque EXIF (segunda imagen embebida en APP1)."""
    if not raw.startswith(b"\xff\xd8"):
        return None
    app1 = raw.find(b"\xff\xe1")
    if app1 < 0 or raw[app1 + 4:app1 + 10] != b"Exif\x00\x00":
        return None
    length = int.from_bytes(raw[app1 + 2:app1 + 4], "big")
    seg = raw[app1 + 4:app1 + 2 + length]
    start = seg.find(b"\xff\xd8\xff")
    end = seg.rfind(b"\xff\xd9")
    if start < 0 or end <= start:
        return None
    try:
        img = Image.open(io.BytesIO(seg[start:end + 2]))
        img.load()
        return img
    except Exception:
        return None


def inspect(img: Image.Image, raw: bytes, name: str, dhash_fn) -> dict:
    """Devuelve los datos crudos que usa signals(); se guarda junto a los metadatos de la foto."""
    exif = img.getexif()
    sub, gps = exif.get_ifd(0x8769), exif.get_ifd(0x8825)
    dates = {"original": _date(sub.get(0x9003)), "digitalizada": _date(sub.get(0x9004)),
             "modificación": _date(exif.get(0x0132))}
    out = {
        "dates": {k: v.isoformat() for k, v in dates.items() if v},
        "offset": str(sub.get(0x9011) or sub.get(0x9010) or "").strip("\x00 ") or None,
        "gps_utc": (g.isoformat() if (g := _gps_utc(gps)) else None),
        "exposure": any(sub.get(t) is not None for t in (0x829A, 0x829D, 0x8827)),
        "user_comment": str(sub.get(0x9286) or "")[:60],
        "tools": sorted({label for marker, label in METADATA_TOOLS.items() if marker in raw}),
        "name": name,
    }
    thumb = _thumbnail(raw)
    if thumb is not None:
        out["thumb_dhash"] = dhash_fn(thumb)
        out["thumb_ratio"] = round(thumb.width / thumb.height, 2)
    return out


def _fmt(dt: datetime) -> str:
    return dt.strftime("%d-%m-%Y %H:%M:%S")


def signals(meta: dict, received: datetime | None, hamming_fn) -> list[tuple[str, str, str, str]]:
    """Lista de (regla, severidad, título, explicación)."""
    f = meta.get("forensics") or {}
    out = []
    dates = {k: datetime.fromisoformat(v) for k, v in (f.get("dates") or {}).items()}

    # 1. fechas internas que no coinciden. Una cámara escribe las tres iguales. Si difiere la de
    #    toma o la de digitalización, alguien las editó; si solo es posterior la de modificación,
    #    el archivo se volvió a guardar (un programa de transferencia también lo hace).
    orig = dates.get("original")
    if orig:
        dig = dates.get("digitalizada")
        mod = dates.get("modificación")
        if dig and abs(dig - orig) > DATE_TOLERANCE:
            out.append(("exif_dates_mismatch", "alta", "Fechas internas de la foto no coinciden",
                        f"La foto dice haberse tomado el {_fmt(orig)}, pero la fecha de digitalización guardada en el "
                        f"mismo archivo es {_fmt(dig)}. Una cámara escribe ambas iguales: los metadatos se editaron."))
        elif mod and mod < orig - DATE_TOLERANCE:
            out.append(("exif_dates_mismatch", "alta", "Fechas internas de la foto no coinciden",
                        f"La foto dice haberse tomado el {_fmt(orig)}, pero dice haberse modificado antes, el "
                        f"{_fmt(mod)}. Es imposible: los metadatos se editaron."))
        elif mod and mod - orig > DATE_TOLERANCE:
            out.append(("exif_resaved", "baja", "La foto se volvió a guardar después de tomada",
                        f"La foto se tomó el {_fmt(orig)} y el archivo se modificó el {_fmt(mod)}. Puede ser una "
                        "edición o solo un programa que copió las fotos; conviene pedir el original."))

    # 2. hora del GPS (UTC) contra fecha de la foto. El GPS puede guardar la última posición
    #    conocida (horas antes), pero nunca una hora posterior a la foto ni días de diferencia.
    if orig and f.get("gps_utc"):
        gps = datetime.fromisoformat(f["gps_utc"])
        off = _offset(f.get("offset"))
        sev = None
        if off is not None:
            diff = (orig - off) - gps          # positivo: el GPS es anterior a la foto
            gap = abs(diff)
            if diff < -GPS_TOLERANCE or diff > timedelta(days=1):
                sev = "alta"
            elif diff > timedelta(hours=1):
                sev = "baja"
        else:
            gap = abs(orig - gps)
            if gap > MAX_TZ + timedelta(days=1):
                sev = "alta"
        if sev:
            hrs = gap.days * 24 + gap.seconds // 3600
            text = (f"El GPS del teléfono registró {_fmt(gps)} (hora UTC), pero la foto dice {_fmt(orig)}"
                    + (f" (zona {f['offset']})" if off is not None else "")
                    + f". Diferencia: {hrs} hora(s). ")
            text += ("Lo más probable es que la fecha de la foto se haya cambiado." if sev == "alta" else
                     "Puede ser una ubicación antigua guardada por el teléfono; conviene revisarla.")
            out.append(("exif_gps_time_mismatch", sev, "La hora del GPS no calza con la fecha de la foto", text))

    # 3. miniatura interna distinta de la imagen
    if f.get("thumb_dhash") and meta.get("dhash"):
        dist = hamming_fn(f["thumb_dhash"], meta["dhash"])
        ratio = meta["width"] / meta["height"] if meta.get("height") else None
        ratio_off = bool(ratio and f.get("thumb_ratio") and abs(ratio - f["thumb_ratio"]) > 0.08
                         and abs(1 / ratio - f["thumb_ratio"]) > 0.08)
        if dist > 20 and not ratio_off:
            out.append(("thumbnail_mismatch", "alta", "La miniatura interna muestra otra imagen",
                        "El archivo guarda una miniatura de la foto original que no coincide con la imagen actual. "
                        "Indica que la imagen se editó y se conservaron los metadatos de la foto original."))
        elif ratio_off:
            out.append(("thumbnail_ratio", "baja", "La miniatura interna tiene otra proporción",
                        "La miniatura guardada en el archivo tiene proporciones distintas a la imagen: puede ser un "
                        "recorte posterior, aunque algunos teléfonos guardan miniaturas de tamaño fijo."))

    # 4. cámara sin datos de exposición
    if meta.get("make") and orig and not f.get("exposure"):
        out.append(("exif_no_exposure", "media", "Datos de cámara incompletos",
                    f"La foto declara cámara {meta.get('make')} {meta.get('model') or ''}".strip()
                    + " y fecha, pero no tiene exposición, apertura ni ISO, que toda cámara registra. "
                      "Es típico de metadatos agregados a mano a una imagen que no salió de esa cámara."))

    # 5. herramientas de reescritura de metadatos
    if f.get("tools"):
        out.append(("metadata_tool", "alta", "Metadatos reescritos con una herramienta",
                    f"El archivo contiene rastros de {', '.join(f['tools'])}, que se usa para escribir o cambiar "
                    "metadatos (fecha, cámara, ubicación)."))

    # 6. fecha en el futuro
    if orig and received and orig - received > timedelta(days=1):
        out.append(("taken_future", "alta", "Fecha de la foto posterior a su recepción",
                    f"La foto dice haberse tomado el {_fmt(orig)}, después de recibirse ({_fmt(received)}). "
                    "La fecha se cambió o el reloj del equipo estaba mal."))

    # 7. captura de pantalla
    why = []
    if "screenshot" in (f.get("user_comment") or "").lower():
        why.append("el sistema la marcó como captura de pantalla")
    if SCREENSHOT_NAME.search(f.get("name") or ""):
        why.append("el nombre del archivo es de una captura")
    w, h = meta.get("width") or 0, meta.get("height") or 0
    if (not f.get("exposure") and meta.get("format") == "PNG" and min(w, h) in PHONE_WIDTHS
            and max(w, h) / max(min(w, h), 1) >= 1.7):
        why.append(f"es PNG de {w}×{h}, tamaño de pantalla de celular, sin datos de cámara")
    if why:
        out.append(("screenshot", "media", "Parece una captura de pantalla",
                    "La imagen parece un pantallazo y no una foto tomada con la cámara: " + "; ".join(why)
                    + ". Un pantallazo no prueba cuándo ni dónde se tomó la imagen original."))
    return out
