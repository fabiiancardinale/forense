"""Lectura completa de una foto: todas las secciones y todos los metadatos que trae el archivo.

Cada marca guarda cosas distintas y en lugares distintos. Este módulo las lee todas y las ordena:

  - Estructura del archivo: segmentos JPEG, bloques PNG/WebP, cajas HEIF, imágenes y videos incrustados
    (mapa de ganancia HDR, foto en movimiento), datos pegados al final del archivo.
  - EXIF completo (todas las carpetas: principal, Exif, GPS, interoperabilidad, miniatura) y nota del
    fabricante (MakerNote) de Apple, Samsung, Google y otras.
  - XMP completo (todas las fuentes y espacios de nombres), incluido el historial de edición y el
    "tipo de origen digital" (IPTC DigitalSourceType) que marca las imágenes hechas o editadas con IA.
  - IPTC / Photoshop (APP13), perfil de color ICC, tablas de compresión JPEG, comentarios.
  - Samsung: sección propia al final del archivo (SEF) con el historial del editor de la galería, uso de
    IA generativa (Galaxy AI), recorte, filtros y si se quitó la marca de IA.
  - Google: cámara (GCamera), contenedor (foto en movimiento, HDR), ediciones con IA de Google.
  - Apple: nota del fabricante (identificador de Live Photo, tipo de captura), HEIC, ajustes de Fotos.
  - C2PA (credenciales de contenido): quién firmó, qué acciones declara (recorte, edición, IA), de qué
    foto se derivó, y si la integridad está intacta (separado de si el emisor está en la lista de confianza).

Resultado: un diccionario con cada sección y tres resúmenes que usa el análisis: "ai" (señales de IA),
"edits" (señales de edición) y "dates" (todas las fechas encontradas).
"""
from __future__ import annotations

import io
import json
import re
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path

MAX_VALUE = 300          # largo máximo de un valor mostrado
MAX_ITEMS = 400          # campos máximos por sección

# ---- textos que delatan IA ------------------------------------------------------------------------
# IPTC DigitalSourceType (estándar que usan Google, Adobe, Meta, Samsung, OpenAI y otros)
DST = {
    "trainedalgorithmicmedia": "imagen generada por IA",
    "compositewithtrainedalgorithmicmedia": "foto con partes generadas o cambiadas por IA",
    "algorithmicmedia": "imagen generada por un algoritmo",
    "compositesynthetic": "composición con elementos sintéticos",
    "algorithmicallyenhanced": "foto mejorada por un algoritmo",
    "digitalart": "arte digital (no es una foto)",
    "virtualrecording": "grabación virtual (no es una foto)",
    "screencapture": "captura de pantalla",
    "compositecapture": "composición de varias capturas",
    "digitalcapture": "captura de cámara",
    "negativefilm": "escaneo de negativo",
    "positivefilm": "escaneo de diapositiva",
    "print": "escaneo de una impresión",
}
DST_AI = {"trainedalgorithmicmedia", "compositewithtrainedalgorithmicmedia", "algorithmicmedia", "compositesynthetic"}
AI_TEXT = re.compile(
    r"(made with ai|edited with ai|ai[- ]generated|ai[- ]edited|generated with ai|edited with google ai|google ai|"
    r"magic editor|magic eraser|best take|reimagine|galaxy ai|generative edit|generative fill|generative expand|"
    r"photo assist|sketch to image|clean ?up|firefly|dall[·-]?e|midjourney|stable diffusion|openai|chatgpt|gpt-4o|"
    r"gpt-image|gemini|imagen [0-9]|meta ai|copilot|bing image creator|leonardo\.ai|ideogram|flux\.|"
    r"contenido generado por ia|generad[oa] (por|con) ia|editad[oa] con ia)", re.I)
EDIT_SOFTWARE = re.compile(
    r"(photoshop|lightroom|gimp|snapseed|picsart|facetune|pixlr|canva|affinity|photopea|meitu|remini|fotor|polarr|"
    r"vsco|airbrush|perfect365|faceapp|inshot|capcut|photo ?editor|picasa|paint\.net|darktable|luminar|pixelmator|"
    r"acdsee|corel|paintshop|krita|inkscape|preview|photos [0-9]|fotos|editor)", re.I)


def _short(v) -> str:
    if isinstance(v, bytes):
        txt = v.decode("utf-8", "ignore").strip("\x00 ")
        if txt and sum(c.isprintable() for c in txt) / len(txt) > 0.9:
            v = txt
        else:
            return f"<{len(v)} bytes>"
    if isinstance(v, (tuple, list)) and len(v) > 12:
        return f"<{len(v)} valores>"
    s = str(v)
    return s if len(s) <= MAX_VALUE else s[:MAX_VALUE] + "…"


# ---- estructura del archivo -----------------------------------------------------------------------
def _jpeg_segments(raw: bytes) -> list[dict]:
    out, i = [], 2
    while i + 4 <= len(raw):
        if raw[i] != 0xFF:
            break
        m = raw[i + 1]
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        L = int.from_bytes(raw[i + 2:i + 4], "big")
        body = raw[i + 4:i + 2 + L]
        out.append({"marker": m, "offset": i, "length": L, "body": body})
        if m == 0xDA:                                   # comienzo de la imagen comprimida
            break
        i += 2 + L
    return out


APP_NAMES = {0xE0: "APP0", 0xE1: "APP1", 0xE2: "APP2", 0xE3: "APP3", 0xE4: "APP4", 0xE5: "APP5", 0xE6: "APP6",
             0xE7: "APP7", 0xE8: "APP8", 0xE9: "APP9", 0xEA: "APP10", 0xEB: "APP11", 0xEC: "APP12", 0xED: "APP13",
             0xEE: "APP14", 0xEF: "APP15", 0xFE: "Comentario", 0xDB: "Tabla de cuantización", 0xC4: "Tabla Huffman",
             0xC0: "Imagen (baseline)", 0xC2: "Imagen (progresiva)", 0xDD: "Reinicio", 0xDA: "Datos"}


def _segment_kind(s: dict) -> str:
    b = s["body"]
    for sig, name in ((b"Exif\x00", "EXIF"), (b"http://ns.adobe.com/xap/1.0/\x00", "XMP"),
                      (b"http://ns.adobe.com/xmp/extension/\x00", "XMP extendido"), (b"ICC_PROFILE\x00", "Perfil ICC"),
                      (b"MPF\x00", "Varias imágenes (MPF)"), (b"JFIF\x00", "JFIF"), (b"Photoshop 3.0\x00", "Photoshop/IPTC"),
                      (b"JP", "JUMBF (C2PA)"), (b"Adobe", "Adobe"), (b"Ducky", "Ducky (Photoshop web)"),
                      (b"urn:iso:std:iso:ts:21496", "Mapa de ganancia HDR (ISO 21496)"), (b"AROT", "Apple AROT"),
                      (b"Meta", "Meta"), (b"HDR_RI", "HDR")):
        if b.startswith(sig):
            return name
    return ""


IJG_LUMA = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29,
            51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92, 49, 64, 78, 87, 103, 121,
            120, 101, 72, 92, 95, 98, 112, 100, 103, 99]
ZIGZAG = [0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21,
          28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61,
          54, 47, 55, 62, 63]


def _quant_tables(segs: list[dict]) -> list[list[int]]:
    tables = []
    for s in segs:
        if s["marker"] != 0xDB:
            continue
        b, i = s["body"], 0
        while i < len(b):
            pq, i = b[i] >> 4, i + 1
            n = 64 * (2 if pq else 1)
            vals = list(b[i:i + n]) if not pq else list(struct.unpack(">64H", b[i:i + n]))
            tables.append([0] * 64)
            for k, v in enumerate(vals[:64]):
                tables[-1][ZIGZAG[k]] = v
            i += n
    return tables


def _ijg_quality(table: list[int]) -> tuple[int | None, bool]:
    """Calidad estimada y si la tabla es exactamente la de libjpeg (la que usan programas, no cámaras)."""
    best, exact = None, False
    for q in range(1, 101):
        scale = 5000 / q if q < 50 else 200 - 2 * q
        ref = [min(255, max(1, (v * scale + 50) // 100)) for v in IJG_LUMA]
        diff = sum(abs(a - b) for a, b in zip(ref, table))
        if best is None or diff < best[1]:
            best = (q, diff)
        if diff == 0:
            exact = True
            break
    return (best[0] if best else None), exact


def _png_chunks(raw: bytes) -> list[tuple[str, bytes]]:
    out, i = [], 8
    while i + 8 <= len(raw):
        L = int.from_bytes(raw[i:i + 4], "big")
        t = raw[i + 4:i + 8].decode("latin1")
        out.append((t, raw[i + 8:i + 8 + L]))
        i += 12 + L
        if t == "IEND":
            break
    return out


def _riff_chunks(raw: bytes) -> list[tuple[str, bytes]]:
    out, i = [], 12
    while i + 8 <= len(raw):
        t = raw[i:i + 4].decode("latin1")
        L = int.from_bytes(raw[i + 4:i + 8], "little")
        out.append((t, raw[i + 8:i + 8 + L]))
        i += 8 + L + (L & 1)
    return out


def _isobmff_boxes(raw: bytes, start=0, end=None, depth=0) -> list[dict]:
    out, i, end = [], start, end or len(raw)
    while i + 8 <= end and len(out) < 200:
        size = int.from_bytes(raw[i:i + 4], "big")
        t = raw[i + 4:i + 8].decode("latin1", "replace")
        hdr = 8
        if size == 1:
            size, hdr = int.from_bytes(raw[i + 8:i + 16], "big"), 16
        elif size == 0:
            size = end - i
        if size < hdr:
            break
        box = {"type": t, "offset": i, "size": size}
        if depth < 2 and t in ("meta", "iprp", "ipco", "moov", "trak"):
            inner = i + hdr + (4 if t == "meta" else 0)
            box["children"] = _isobmff_boxes(raw, inner, i + size, depth + 1)
        out.append(box)
        i += size
    return out


# ---- EXIF y nota del fabricante -------------------------------------------------------------------
def _exif_all(img) -> tuple[dict, dict]:
    from PIL import ExifTags
    exif = img.getexif()
    out, raw_tags = {}, {}
    groups = [("Principal", dict(exif))]
    for ifd_id, name in ((0x8769, "Exif"), (0x8825, "GPS"), (0xA005, "Interoperabilidad")):
        try:
            groups.append((name, dict(exif.get_ifd(ifd_id))))
        except Exception:
            pass
    try:
        groups.append(("Miniatura", dict(exif.get_ifd(1)) if hasattr(exif, "get_ifd") else {}))
    except Exception:
        pass
    for gname, tags in groups:
        names = ExifTags.GPSTAGS if gname == "GPS" else ExifTags.TAGS
        for k, v in tags.items():
            if k in (0x8769, 0x8825, 0xA005):
                continue
            label = names.get(k, f"0x{k:04X}")
            raw_tags[(gname, label)] = v
            if k == 0x927C:                     # la nota del fabricante se lee aparte
                out[f"{gname}: MakerNote"] = f"<{len(v)} bytes>" if isinstance(v, bytes) else _short(v)
                continue
            out[f"{gname}: {label}"] = _short(v)
            if len(out) >= MAX_ITEMS:
                break
    return out, raw_tags


def _tiff_ifd(buf: bytes, off: int, endian: str, base: int = 0, limit: int = 120) -> dict:
    """Lee una carpeta TIFF (lista de campos) sin seguir subcarpetas. Para notas del fabricante."""
    out = {}
    try:
        n = struct.unpack(endian + "H", buf[off:off + 2])[0]
    except struct.error:
        return out
    sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8}
    for k in range(min(n, limit)):
        e = off + 2 + 12 * k
        if e + 12 > len(buf):
            break
        tag, typ, cnt = struct.unpack(endian + "HHI", buf[e:e + 8])
        size = sizes.get(typ, 1) * cnt
        data = buf[e + 8:e + 12] if size <= 4 else buf[base + struct.unpack(endian + "I", buf[e + 8:e + 12])[0]:][:min(size, 4096)]
        try:
            if typ == 2:
                val = data[:size].split(b"\x00")[0].decode("utf-8", "ignore")
            elif typ == 3:
                val = list(struct.unpack(endian + f"{min(cnt, 64)}H", data[:2 * min(cnt, 64)]))
            elif typ in (4, 9):
                val = list(struct.unpack(endian + f"{min(cnt, 64)}{'I' if typ == 4 else 'i'}", data[:4 * min(cnt, 64)]))
            elif typ in (5, 10):
                nums = struct.unpack(endian + f"{2 * min(cnt, 32)}{'I' if typ == 5 else 'i'}", data[:8 * min(cnt, 32)])
                val = [round(nums[j] / nums[j + 1], 6) if nums[j + 1] else 0 for j in range(0, len(nums), 2)]
            else:
                val = data[:size]
        except struct.error:
            val = data[:size]
        if isinstance(val, list) and len(val) == 1:
            val = val[0]
        out[tag] = val
    return out


APPLE_TAGS = {0x0001: "Versión de la nota", 0x0003: "Tiempo desde el encendido", 0x0004: "Estado AE",
              0x0008: "Vector de aceleración (orientación del teléfono)", 0x000A: "Tipo de HDR",
              0x000B: "Identificador de ráfaga", 0x000C: "Rango de enfoque", 0x000F: "Estado OIS",
              0x0011: "Identificador de Live Photo / contenido", 0x0014: "Tipo de captura",
              0x0015: "Identificador único de imagen", 0x0017: "Live Photo: índice de video",
              0x0019: "Brillo de la escena", 0x001A: "Calidad de la foto", 0x001F: "Funciones de la app Fotos",
              0x0020: "Identificador de la solicitud de captura", 0x0021: "HDR de cabeza", 0x0023: "Estado AF",
              0x0025: "Caras detectadas", 0x002B: "Identificador de foto", 0x002E: "Modo de cámara",
              0x002F: "Posición del enfoque", 0x0030: "Escena", 0x0036: "Fusión de imágenes (Deep Fusion)",
              0x003A: "Modo nocturno", 0x003F: "Zoom", 0x0040: "Efecto semántico", 0x0043: "Posición de la lente",
              0x004A: "Estilo fotográfico"}
APPLE_CAPTURE = {1: "Foto ProRAW", 2: "Retrato", 10: "Foto", 11: "Foto manual", 12: "Escena"}


def _makernote(raw_tags: dict, make: str) -> dict:
    mn = raw_tags.get(("Exif", "MakerNote"))
    if not isinstance(mn, bytes) or not mn:
        return {}
    out = {"Fabricante (según EXIF)": make or "—", "Tamaño": f"{len(mn)} bytes"}
    if mn.startswith(b"Apple iOS\x00"):
        out["Formato"] = "Apple iOS"
        endian = ">" if mn[12:14] == b"MM" else "<"
        fields = _tiff_ifd(mn, 14, endian, base=0)
        for k, v in fields.items():
            name = APPLE_TAGS.get(k, f"Apple 0x{k:04X}")
            if k == 0x0014 and isinstance(v, int):
                v = f"{v} ({APPLE_CAPTURE.get(v, 'otro')})"
            out[name] = _short(v)
    elif mn.startswith((b"Samsung", b"\x07\x00")) or "samsung" in (make or "").lower():
        out["Formato"] = "Samsung"
        endian = "<" if mn[:2] != b"MM" else ">"
        for k, v in _tiff_ifd(mn, 0, endian, base=0).items():
            out[f"Samsung 0x{k:04X}"] = _short(v)
    elif mn.startswith(b"HUAWEI"):
        out["Formato"] = "Huawei"
    elif mn.startswith((b"Nikon", b"OLYMPUS", b"FUJIFILM", b"Panasonic", b"SONY", b"QVC", b"Ricoh", b"LEICA", b"Pentax")):
        out["Formato"] = mn[:10].split(b"\x00")[0].decode("latin1", "ignore")
    else:
        endian = "<"
        fields = _tiff_ifd(mn, 0, endian)
        if fields and len(fields) < 200:
            out["Formato"] = "carpeta TIFF"
            for k, v in list(fields.items())[:60]:
                out[f"0x{k:04X}"] = _short(v)
        else:
            out["Formato"] = "desconocido"
    return out


# ---- XMP ------------------------------------------------------------------------------------------
def _xmp_packets(raw: bytes, segs: list[dict] | None, chunks: list[tuple[str, bytes]] | None) -> list[str]:
    packets = []
    for m in re.finditer(rb"<x:xmpmeta.*?</x:xmpmeta>", raw, re.S):
        packets.append(m.group(0).decode("utf-8", "ignore"))
    if segs:                                                  # XMP extendido (Google, Adobe): trozos por GUID
        ext = {}
        for s in segs:
            b = s["body"]
            if b.startswith(b"http://ns.adobe.com/xmp/extension/\x00"):
                b = b[35:]
                guid, off = b[:32], int.from_bytes(b[36:40], "big")
                ext.setdefault(guid, []).append((off, b[40:]))
        for parts in ext.values():
            data = b"".join(p for _, p in sorted(parts))
            packets.append(data.decode("utf-8", "ignore"))
    if chunks:
        for t, data in chunks:
            if t in ("iTXt", "zTXt", "tEXt") and data.startswith(b"XML:com.adobe.xmp"):
                continue                                     # ya lo encontró la búsqueda general
    return packets


def _xmp_parse(packets: list[str]) -> dict:
    """Todos los campos XMP como 'prefijo:nombre' → valor (atributos, elementos y listas)."""
    out: dict[str, str] = {}

    def put(key, val):
        val = " ".join(str(val).split())
        if not val or key.startswith(("xmlns", "rdf:", "x:")):
            return
        if key in out and val not in out[key]:
            out[key] = (out[key] + " | " + val)[:MAX_VALUE * 3]
        elif key not in out:
            out[key] = val[:MAX_VALUE * 3]
    for pkt in packets:
        for m in re.finditer(r'([A-Za-z][\w.-]*:[\w.-]+)\s*=\s*"([^"]*)"', pkt):
            put(m.group(1), m.group(2))
        for m in re.finditer(r"<([A-Za-z][\w.-]*:[\w.-]+)(?:\s[^>]*)?>([^<]+)</\1>", pkt):
            put(m.group(1), m.group(2))
        for m in re.finditer(r"<([A-Za-z][\w.-]*:[\w.-]+)(?:\s[^>]*)?>\s*<rdf:(?:Seq|Bag|Alt)>(.*?)</rdf:(?:Seq|Bag|Alt)>",
                             pkt, re.S):
            items = re.findall(r"<rdf:li[^>]*>([^<]*)</rdf:li>", m.group(2))
            if items:
                put(m.group(1), ", ".join(i.strip() for i in items if i.strip()))
        for m in re.finditer(r"<(?:stEvt|stRef):([\w]+)>([^<]*)<", pkt):
            put("historial:" + m.group(1), m.group(2))
        if len(out) >= MAX_ITEMS:
            break
    return out


# ---- IPTC / Photoshop -----------------------------------------------------------------------------
IIM = {0: "Versión del registro", 5: "Título", 25: "Palabras clave", 40: "Instrucciones", 55: "Fecha de creación", 60: "Hora de creación",
       62: "Fecha digital", 63: "Hora digital", 65: "Programa", 70: "Versión del programa", 80: "Autor",
       85: "Cargo del autor", 90: "Ciudad", 95: "Región", 101: "País", 105: "Titular", 110: "Crédito",
       115: "Fuente", 116: "Copyright", 120: "Descripción", 122: "Redactor"}
PS_RESOURCES = {0x0404: "IPTC", 0x0425: "Resumen IPTC (MD5)", 0x040C: "Miniatura", 0x0409: "Miniatura (antigua)",
                0x03ED: "Resolución", 0x040F: "Perfil ICC", 0x0422: "EXIF (Photoshop)", 0x0424: "XMP (Photoshop)",
                0x0421: "Versión de Photoshop", 0x0406: "Calidad JPEG de Photoshop", 0x041A: "Divisiones (slices)",
                0x0408: "Guías", 0x0400: "Capas", 0x0402: "Capas seleccionadas"}


def _iptc(segs: list[dict]) -> dict:
    out = {}
    for s in segs:
        b = s["body"]
        if not b.startswith(b"Photoshop 3.0\x00"):
            continue
        i = 14
        while i + 12 <= len(b) and b[i:i + 4] == b"8BIM":
            rid = int.from_bytes(b[i + 4:i + 6], "big")
            nlen = b[i + 6]
            j = i + 7 + nlen
            j += (j - i) & 1
            size = int.from_bytes(b[j:j + 4], "big")
            data = b[j + 4:j + 4 + size]
            out[f"Recurso Photoshop {PS_RESOURCES.get(rid, hex(rid))}"] = f"{size} bytes"
            if rid == 0x0404:
                k = 0
                while k + 5 <= len(data) and data[k] == 0x1C:
                    rec, ds, ln = data[k + 1], data[k + 2], int.from_bytes(data[k + 3:k + 5], "big")
                    val = data[k + 5:k + 5 + ln].decode("utf-8", "ignore")
                    if rec == 2:
                        key = f"IPTC {IIM.get(ds, ds)}"
                        out[key] = (out[key] + ", " + val) if key in out else val
                    k += 5 + ln
            i = j + 4 + size + (size & 1)
    return out


# ---- ICC ------------------------------------------------------------------------------------------
def _icc(img, segs) -> dict:
    data = img.info.get("icc_profile")
    if not data and segs:
        parts = [s["body"][14:] for s in segs if s["body"].startswith(b"ICC_PROFILE\x00")]
        data = b"".join(parts) or None
    if not data or len(data) < 132:
        return {}
    out = {"Tamaño": f"{len(data)} bytes", "Programa que lo creó (CMM)": data[4:8].decode("latin1").strip("\x00 "),
           "Fabricante del dispositivo": data[48:52].decode("latin1").strip("\x00 "),
           "Creador del perfil": data[80:84].decode("latin1").strip("\x00 ")}
    try:
        y, mo, d, h, mi, s = struct.unpack(">6H", data[24:36])
        out["Fecha del perfil"] = f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"
    except struct.error:
        pass
    try:
        n = int.from_bytes(data[128:132], "big")
        for k in range(min(n, 40)):
            sig, off, ln = struct.unpack(">4sII", data[132 + 12 * k:144 + 12 * k])
            if sig in (b"desc", b"cprt", b"dmnd", b"dmdd"):
                el = data[off:off + ln]
                if el[:4] == b"desc":
                    txt = el[12:12 + int.from_bytes(el[8:12], "big")].split(b"\x00")[0].decode("latin1", "ignore")
                elif el[:4] == b"mluc":
                    rec_off, rec_len = int.from_bytes(el[20:24], "big"), int.from_bytes(el[24:28], "big")
                    txt = el[rec_off:rec_off + rec_len].decode("utf-16-be", "ignore")
                else:
                    txt = el[8:].split(b"\x00")[0].decode("latin1", "ignore")
                out[{"desc": "Nombre", "cprt": "Copyright", "dmnd": "Marca", "dmdd": "Modelo"}[sig.decode()]] = txt.strip()
    except (struct.error, KeyError):
        pass
    return {k: v for k, v in out.items() if v}


# ---- Samsung: sección SEF al final del archivo -----------------------------------------------------
SEF_NAMES = {"Image_UTC_Data": "Hora UTC de la foto", "PEg_Info": "IA generativa del editor (Galaxy AI)",
             "PhotoEditor_Re_Edit_Data": "Historial del editor de la galería", "Original_Path_Hash_Key": "Huella del original",
             "MotionPhoto_Data": "Foto en movimiento", "MotionPhoto_Version": "Foto en movimiento (versión)",
             "Camera_Capture_Mode_Info": "Modo de cámara", "Dual_Camera_Info": "Cámara doble",
             "Camera_Scene_Info": "Escena detectada", "Burst_Shot_Info": "Ráfaga", "Food_Shot_Info": "Modo comida",
             "Color_Display_P3": "Color P3", "Single_Take_Info": "Toma única", "Remaster_Info": "Remasterizada",
             "Object_Eraser_Info": "Borrador de objetos", "Shadow_Eraser_Info": "Borrador de sombras",
             "Reflection_Eraser_Info": "Borrador de reflejos", "Generative_Edit": "Edición generativa",
             "AI_Edit_Info": "Edición con IA", "Watermark_Info": "Marca de agua"}


def _samsung_sef(raw: bytes) -> dict:
    """Lee la tabla SEF (Samsung Extended Format) del final del archivo: nombre → contenido."""
    if not raw.endswith(b"SEFT") or raw[-8:-4] == b"":
        return {}
    try:
        dir_len = int.from_bytes(raw[-8:-4], "little")
        start = len(raw) - 8 - dir_len
        d = raw[start:len(raw) - 8]
        if d[:4] != b"SEFH":
            return {}
        count = int.from_bytes(d[8:12], "little")
        out = {}
        for k in range(min(count, 64)):
            e = 12 + 12 * k
            off, ln = struct.unpack("<II", d[e + 4:e + 12])     # distancia hacia atrás desde la tabla y largo
            blk = raw[start - off:start - off + ln]
            nlen = int.from_bytes(blk[4:8], "little")
            name = blk[8:8 + nlen].decode("latin1", "ignore")
            out[name] = blk[8 + nlen:]
        return out
    except (struct.error, ValueError):
        return {}


def _sef_fallback(raw: bytes) -> dict:
    """Si la tabla no se puede leer, busca los nombres conocidos en el final del archivo."""
    tail = raw[-200_000:]
    out = {}
    for name in SEF_NAMES:
        i = tail.find(name.encode())
        if i >= 0:
            rest = tail[i + len(name):i + len(name) + 4000]
            m = re.match(rb"(\{.*?\})(?:\x00|$)", rest, re.S) or re.match(rb"([ -~]{1,200})", rest)
            out[name] = m.group(1) if m else b""
    return out


def _samsung(raw: bytes) -> tuple[dict, dict]:
    entries = _samsung_sef(raw) or (_sef_fallback(raw) if b"SEFH" in raw[-200_000:] else {})
    if not entries:
        return {}, {}
    shown, parsed = {}, {}
    for name, val in entries.items():
        text = val.decode("utf-8", "ignore").strip("\x00 ") if isinstance(val, bytes) else str(val)
        label = SEF_NAMES.get(name, name)
        data = None
        if text.startswith("{"):
            try:
                data = json.loads(text)
            except ValueError:
                data = None
        if name == "Image_UTC_Data" and text.isdigit():
            ts = datetime.fromtimestamp(int(text) / 1000, timezone.utc).replace(tzinfo=None)
            parsed["utc"] = ts.isoformat(timespec="seconds")
            text = parsed["utc"] + " UTC"
        if data is not None:
            parsed[name] = data
        shown[label] = _short(text) if text and sum(c.isprintable() for c in text) > 0.8 * len(text) else f"<{len(val)} bytes>"
    return shown, parsed


def _samsung_edits(parsed: dict) -> tuple[list[str], list[str], bool]:
    """Qué cambió el editor de Samsung. Devuelve (ediciones, IA, marca de IA quitada)."""
    edits, ai, wm_removed = [], [], False
    peg = parsed.get("PEg_Info")
    if isinstance(peg, dict) and (peg.get("genAIType") or peg.get("genImageVersion")):
        ai.append(f"Samsung Galaxy AI: edición generativa en la galería (genAIType {peg.get('genAIType')})")
    for k in ("Object_Eraser_Info", "Generative_Edit", "AI_Edit_Info", "Reflection_Eraser_Info", "Shadow_Eraser_Info"):
        if k in parsed or k in parsed.get("_names", ()):
            ai.append(f"Samsung: {SEF_NAMES.get(k, k)}")
    re_edit = parsed.get("PhotoEditor_Re_Edit_Data")
    if isinstance(re_edit, dict):
        def sub(key):
            v = re_edit.get(key)
            try:
                return json.loads(v) if isinstance(v, str) else (v or {})
            except ValueError:
                return {}
        clip = sub("clipInfoValue")
        if clip and (abs(clip.get("mWidth", 1) - 1) > 0.005 or abs(clip.get("mHeight", 1) - 1) > 0.005):
            edits.append(f"Recorte en la galería: quedó {round(clip.get('mWidth', 1) * 100)}% de ancho y "
                         f"{round(clip.get('mHeight', 1) * 100)}% de alto")
        if clip and any(clip.get(k) for k in ("mRotation", "mRotate", "mHFlip", "mVFlip", "mHozPerspective", "mVerPerspective")):
            edits.append("Rotación, espejo o perspectiva cambiados en la galería")
        tone = sub("toneValue")
        changed = [k for k, v in tone.items() if isinstance(v, (int, float)) and not isinstance(v, bool)
                   and k not in ("wbMode",) and v != 100]
        if changed:
            edits.append("Ajustes de luz o color cambiados: " + ", ".join(changed))
        eff = sub("effectValue")
        if eff.get("filterType") not in (None, 0):
            edits.append("Filtro aplicado en la galería")
        portrait = sub("portraitEffectValue")
        if portrait.get("waterMarkRemoved") or portrait.get("waterMarkRemovedOriginal"):
            wm_removed = True
        if re_edit.get("isScaleAI"):
            ai.append("Samsung: imagen ampliada con IA")
        if re_edit.get("isAIFilterReEditOnly") or re_edit.get("isApplyShapeCorrection"):
            ai.append("Samsung: filtro o corrección con IA")
        if not edits and not ai:
            edits.append("Pasó por el editor de la galería de Samsung")
    return edits, ai, wm_removed


# ---- C2PA -----------------------------------------------------------------------------------------
TRUST_CODES = ("signingCredential.untrusted", "signingCredential.invalid", "signingCredential.ocsp", "timeStamp.untrusted")


def c2pa_full(path) -> dict:
    try:
        import c2pa
    except ImportError:
        return {"note": "no se pudo revisar (falta la librería c2pa-python)"}
    try:
        settings = c2pa.Settings.from_dict({"verify": {"fetch_remote_manifests": False, "fetch_ocsp": False}})
        with settings, c2pa.Context(settings=settings) as context, c2pa.Reader(str(path), context=context) as reader:
            j = json.loads(reader.json())
    except Exception as ex:
        msg = str(ex)
        if "ManifestNotFound" in type(ex).__name__ or "not found" in msg.lower() or "JumbfNotFound" in msg:
            return {}
        return {"error": type(ex).__name__}
    if not j.get("manifests"):
        return {}
    m = j["manifests"].get(j.get("active_manifest"), {})
    status = j.get("validation_status") or []
    problems = [s for s in status if not str(s.get("code", "")).startswith(TRUST_CODES)]
    trust = [s for s in status if str(s.get("code", "")).startswith(TRUST_CODES)]
    actions, sources, agents = [], [], []
    for a in m.get("assertions", []) or []:
        if str(a.get("label", "")).startswith("c2pa.actions"):
            for act in (a.get("data") or {}).get("actions", []):
                actions.append(act.get("action"))
                if act.get("digitalSourceType"):
                    sources.append(str(act["digitalSourceType"]).rsplit("/", 1)[-1])
                ag = act.get("softwareAgent")
                if ag:
                    agents.append(ag if isinstance(ag, str) else ag.get("name", ""))
    sig = m.get("signature_info") or {}
    return {
        "generator": m.get("claim_generator") or ", ".join(g.get("name", "") for g in m.get("claim_generator_info") or []),
        "state": j.get("validation_state"),
        "integrity_ok": not problems,
        "trusted": not trust,
        "problems": [f"{p.get('code')}: {p.get('explanation', '')}" for p in problems][:6],
        "trust_notes": [f"{p.get('code')}: {p.get('explanation', '')}" for p in trust][:4],
        "issuer": sig.get("issuer") or sig.get("common_name"), "signed": sig.get("time"),
        "actions": [a for a in actions if a], "sources": sources, "agents": [a for a in agents if a],
        "ingredients": [{"title": i.get("title"), "relationship": i.get("relationship")}
                        for i in m.get("ingredients", []) or []],
        "manifests": len(j["manifests"]),
    }


# ---- lectura completa ------------------------------------------------------------------------------
def read_all(path, raw: bytes | None = None) -> dict:
    from PIL import Image
    path = Path(path)
    raw = raw if raw is not None else path.read_bytes()
    res: dict = {"archivo": {}, "estructura": [], "exif": {}, "fabricante": {}, "xmp": {}, "iptc": {}, "icc": {},
                 "samsung": {}, "google": {}, "apple": {}, "c2pa": {}, "png": {}, "jpeg": {},
                 "ai": [], "edits": [], "dates": {}, "flags": {}}
    segs = chunks = None
    kind = ("JPEG" if raw[:2] == b"\xff\xd8" else "PNG" if raw[:8] == b"\x89PNG\r\n\x1a\n" else
            "WEBP" if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP" else
            "HEIF" if raw[4:8] == b"ftyp" else "TIFF" if raw[:4] in (b"II*\x00", b"MM\x00*") else "otro")
    res["archivo"] = {"Formato según el contenido": kind, "Tamaño": f"{len(raw):,} bytes".replace(",", "."),
                      "Nombre": path.name}
    # estructura
    try:
        if kind == "JPEG":
            segs = _jpeg_segments(raw)
            for s in segs:
                res["estructura"].append(f"{APP_NAMES.get(s['marker'], hex(s['marker']))} "
                                         f"{_segment_kind(s)} ({s['length']} bytes)".replace("  ", " "))
            # imágenes incrustadas y datos tras el final
            starts = [m.start() for m in re.finditer(rb"\xff\xd8\xff", raw)][1:]
            if starts:
                res["archivo"]["Imágenes incrustadas"] = f"{len(starts)} (miniatura, mapa HDR o profundidad)"
            mp4 = raw.find(b"ftypmp4") if b"ftypmp4" in raw else raw.find(b"ftypisom")
            if mp4 > 0:
                res["archivo"]["Video incrustado"] = f"sí, foto en movimiento ({(len(raw) - mp4 + 4):,} bytes)".replace(",", ".")
                res["flags"]["motion"] = True
            last_eoi = raw.rfind(b"\xff\xd9")
            if 0 < last_eoi < len(raw) - 2:
                res["archivo"]["Datos después del final de la imagen"] = f"{len(raw) - last_eoi - 2} bytes"
            com = [s["body"].decode("utf-8", "ignore") for s in segs if s["marker"] == 0xFE]
            if com:
                res["jpeg"]["Comentario"] = _short(" | ".join(com))
            tables = _quant_tables(segs)
            if tables:
                q, exact = _ijg_quality(tables[0])
                res["jpeg"]["Calidad estimada"] = q
                res["jpeg"]["Tablas de compresión"] = ("estándar de libjpeg (típicas de programas y apps, no de la cámara)"
                                                       if exact else "propias (típicas de la cámara del teléfono)")
                res["flags"]["standard_tables"] = exact
            sof = next((s for s in segs if s["marker"] in (0xC0, 0xC1, 0xC2)), None)
            if sof:
                b = sof["body"]
                comps = b[5]
                samp = [f"{b[6 + 3 * k + 1] >> 4}x{b[6 + 3 * k + 1] & 15}" for k in range(comps)]
                res["jpeg"]["Tipo"] = "progresivo" if sof["marker"] == 0xC2 else "base"
                res["jpeg"]["Submuestreo de color"] = " ".join(samp)
            jfif = next((s for s in segs if s["body"].startswith(b"JFIF\x00")), None)
            if jfif:
                res["jpeg"]["JFIF"] = f"versión {jfif['body'][5]}.{jfif['body'][6]:02d}"
        elif kind == "PNG":
            chunks = _png_chunks(raw)
            res["estructura"] = [f"{t} ({len(d)} bytes)" for t, d in chunks if t != "IDAT"] + \
                                [f"IDAT × {sum(1 for t, _ in chunks if t == 'IDAT')}"]
            for t, d in chunks:
                if t in ("tEXt", "zTXt", "iTXt"):
                    key, _, rest = d.partition(b"\x00")
                    k = key.decode("latin1")
                    if t == "zTXt":
                        rest = zlib.decompress(rest[1:]) if rest[:1] == b"\x00" else rest
                    elif t == "iTXt":
                        flag = rest[0:1]
                        parts = rest[2:].split(b"\x00", 2)
                        rest = parts[2] if len(parts) == 3 else b""
                        if flag == b"\x01":
                            try:
                                rest = zlib.decompress(rest)
                            except zlib.error:
                                pass
                    if not k.startswith("XML:com.adobe.xmp"):
                        res["png"][f"Texto «{k}»"] = _short(rest)
                elif t == "tIME" and len(d) == 7:
                    y, mo, dd, h, mi, s = struct.unpack(">HBBBBB", d)
                    res["png"]["Fecha de modificación (tIME)"] = f"{y:04d}-{mo:02d}-{dd:02d}T{h:02d}:{mi:02d}:{s:02d}"
                    res["dates"]["PNG tIME (UTC)"] = res["png"]["Fecha de modificación (tIME)"]
                elif t == "caBX":
                    res["png"]["Credenciales C2PA"] = f"sí ({len(d)} bytes)"
                elif t == "eXIf":
                    res["png"]["EXIF dentro del PNG"] = f"{len(d)} bytes"
                elif t == "iCCP":
                    res["png"]["Perfil de color"] = d.split(b"\x00")[0].decode("latin1")
        elif kind == "WEBP":
            chunks = _riff_chunks(raw)
            res["estructura"] = [f"{t} ({len(d)} bytes)" for t, d in chunks]
        elif kind == "HEIF":
            boxes = _isobmff_boxes(raw)
            res["archivo"]["Marca HEIF"] = raw[8:12].decode("latin1")
            res["estructura"] = [f"{b['type']} ({b['size']} bytes)" +
                                 (": " + ", ".join(c["type"] for c in b.get("children", [])) if b.get("children") else "")
                                 for b in boxes]
    except Exception as ex:                                    # una estructura rara no frena el resto
        res["archivo"]["Estructura"] = f"no se pudo leer completa ({type(ex).__name__})"

    # EXIF, nota del fabricante, ICC
    raw_tags: dict = {}
    try:
        if kind == "HEIF":
            try:
                from pillow_heif import register_heif_opener
                register_heif_opener()
            except ImportError:
                pass
        with Image.open(io.BytesIO(raw)) as img:
            res["archivo"]["Dimensiones"] = f"{img.width}×{img.height}"
            res["archivo"]["Modo de color"] = img.mode
            res["exif"], raw_tags = _exif_all(img)
            make = str(raw_tags.get(("Principal", "Make"), "") or "")
            res["fabricante"] = _makernote(raw_tags, make)
            res["icc"] = _icc(img, segs)
            for k in ("dpi", "progressive", "jfif_version"):
                if k in img.info:
                    res["archivo"][{"dpi": "Resolución (ppp)", "progressive": "Progresivo",
                                    "jfif_version": "Versión JFIF"}[k]] = _short(img.info[k])
            if kind == "HEIF" and img.info.get("xmp"):
                raw += b"\n" + (img.info["xmp"] if isinstance(img.info["xmp"], bytes) else str(img.info["xmp"]).encode())
    except Exception as ex:
        res["archivo"]["Lectura"] = f"la imagen no se pudo abrir ({type(ex).__name__})"

    # XMP
    try:
        res["xmp"] = _xmp_parse(_xmp_packets(raw, segs, chunks))
    except Exception:
        res["xmp"] = {}
    # IPTC / Photoshop
    if segs:
        try:
            res["iptc"] = _iptc(segs)
        except Exception:
            pass
    # Samsung
    sam_shown, sam = _samsung(raw)
    res["samsung"] = sam_shown
    if sam.get("utc"):
        res["dates"]["Samsung: hora UTC"] = sam["utc"]
    sam_edits, sam_ai, wm_removed = _samsung_edits(sam)
    res["edits"] += sam_edits
    res["ai"] += sam_ai
    if wm_removed:
        res["flags"]["ai_watermark_removed"] = True
    if sam_shown:
        res["flags"]["samsung_editor"] = "PhotoEditor_Re_Edit_Data" in sam or "PEg_Info" in sam

    # Google y Apple (vistas por fabricante a partir de XMP y nota del fabricante)
    x = res["xmp"]
    res["google"] = {k: v for k, v in x.items() if k.split(":")[0] in ("GCamera", "GContainer", "Container", "Item",
                                                                        "GDepth", "GImage", "GPano", "hdrgm", "GFocus")}
    if any(k.startswith(("GCamera:MotionPhoto", "GCamera:MicroVideo")) for k in x):
        res["flags"]["motion"] = True
    res["apple"] = {k: v for k, v in res["fabricante"].items()} if res["fabricante"].get("Formato") == "Apple iOS" else {}
    for k, v in x.items():
        if k.split(":")[0] in ("apple-fi", "AppleDesktop", "aux", "photoshop") and "apple" in (res["exif"].get("Principal: Make", "").lower()):
            res["apple"][k] = v

    # C2PA
    if b"jumb" in raw or b"c2pa" in raw or (chunks and any(t == "caBX" for t, _ in chunks)):
        res["c2pa"] = c2pa_full(path) if path.exists() else {}
    c = res["c2pa"]
    for src in c.get("sources", []):
        if src.lower() in DST_AI:
            res["ai"].append(f"Credencial C2PA: {DST.get(src.lower(), src)} ({', '.join(c.get('agents') or []) or c.get('generator')})")
    for act in c.get("actions", []):
        if act in ("c2pa.cropped", "c2pa.edited", "c2pa.filtered", "c2pa.color_adjustments", "c2pa.resized",
                   "c2pa.orientation", "c2pa.drawing", "c2pa.removed", "c2pa.placed", "c2pa.converted"):
            res["edits"].append(f"Credencial C2PA declara la acción «{act.split('.', 1)[1]}»")
    for ing in c.get("ingredients", []):
        if ing.get("relationship") == "parentOf":
            res["edits"].append(f"Credencial C2PA: se hizo a partir de otra foto ({ing.get('title') or 'sin nombre'})")
    if c and c.get("integrity_ok") is False:
        res["flags"]["c2pa_broken"] = True

    # IA y edición en XMP, IPTC, EXIF y textos
    for k, v in x.items():
        lk = k.lower()
        if lk.endswith("digitalsourcetype"):
            src = v.rsplit("/", 1)[-1].strip().lower()
            if src in DST_AI:
                res["ai"].append(f"XMP {k}: {DST.get(src, src)}")
            elif src in DST and src != "digitalcapture":
                res["edits"].append(f"XMP {k}: {DST[src]}")
        if lk.startswith("crs:") and k not in ("crs:Version", "crs:ProcessVersion", "crs:RawFileName"):
            res["flags"]["lightroom"] = True
        if lk in ("xmp:creatortool", "historial:softwareagent", "tiff:software", "photoshop:history"):
            if EDIT_SOFTWARE.search(v) and not re.search(r"^(?:[A-Z]?\d|samsung|apple|google|pixel)", v.strip(), re.I):
                res["edits"].append(f"Programa de edición en XMP ({k}): {v[:80]}")
        if k == "historial:action" and re.search(r"saved|converted|derived|edited|produced", v):
            res["edits"].append(f"Historial de edición XMP: {v[:120]}")
    if res["flags"].get("lightroom"):
        res["edits"].append("Ajustes de Lightroom / Camera Raw guardados en el archivo")
    if res["iptc"].get("Recurso Photoshop Versión de Photoshop") or any("Capas" in k for k in res["iptc"]):
        res["edits"].append("El archivo pasó por Photoshop (recursos de Photoshop dentro del JPEG)")
    texts = list(x.values()) + list(res["iptc"].values()) + list(res["png"].values()) + \
        [v for k, v in res["exif"].items() if k.endswith(("Software", "ImageDescription", "UserComment", "Artist",
                                                          "XPComment", "XPKeywords", "MakerNote"))]
    for t in texts:
        m = AI_TEXT.search(str(t))
        if m and not any(m.group(0).lower() in a.lower() for a in res["ai"]):
            res["ai"].append(f"Texto en los metadatos: «{m.group(0)}» ({str(t)[:90]})")
    for k in ("parameters", "prompt", "workflow", "Dream", "sd-metadata", "invokeai_metadata"):
        if f"Texto «{k}»" in res["png"]:
            res["ai"].append(f"PNG con datos de generador de imágenes («{k}»)")

    # fechas de todas las fuentes
    for key, label in (("Exif: DateTimeOriginal", "EXIF: tomada"), ("Exif: DateTimeDigitized", "EXIF: digitalizada"),
                       ("Principal: DateTime", "EXIF: modificada"), ("GPS: GPSDateStamp", "GPS: fecha UTC")):
        if res["exif"].get(key):
            res["dates"][label] = res["exif"][key]
    for k in ("xmp:CreateDate", "xmp:ModifyDate", "xmp:MetadataDate", "photoshop:DateCreated", "exif:DateTimeOriginal",
              "Iptc4xmpCore:DateCreated", "historial:when"):
        if x.get(k):
            res["dates"]["XMP " + k] = x[k]
    if res["iptc"].get("IPTC Fecha de creación"):
        res["dates"]["IPTC: creación"] = res["iptc"]["IPTC Fecha de creación"] + " " + res["iptc"].get("IPTC Hora de creación", "")
    if res["icc"].get("Fecha del perfil"):
        res["dates"]["ICC: perfil"] = res["icc"]["Fecha del perfil"]
    if c.get("signed"):
        res["dates"]["C2PA: firmada"] = str(c["signed"])
    res["ai"] = list(dict.fromkeys(res["ai"]))
    res["edits"] = list(dict.fromkeys(res["edits"]))
    return res


def compact(res: dict) -> dict:
    """Versión reducida que se guarda con el análisis (sin las tablas completas)."""
    return {"ai": res.get("ai", []), "edits": res.get("edits", []), "flags": res.get("flags", {}),
            "dates": res.get("dates", {}), "c2pa": res.get("c2pa", {}),
            "maker": res.get("fabricante", {}).get("Formato")}
