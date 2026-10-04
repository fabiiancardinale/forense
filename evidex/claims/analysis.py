"""Siniestros de seguros de autos: forense de las fotos que respaldan un reclamo.

Qué revisa en cada foto:
  1. Marcas de generación por IA (C2PA "trainedAlgorithmicMedia", parámetros de
     Stable Diffusion/ComfyUI, nombres de generadores).
  2. Edición con software (Photoshop, Snapseed, PicsArt, etc.).
  3. Ausencia de metadatos (típico de fotos reenviadas por WhatsApp o capturas).
  4. Fecha de la foto contra la fecha declarada del siniestro.
  5. Ubicación GPS de la foto contra el lugar declarado.
  6. Reutilización: la misma foto (o una casi idéntica, recortada, recomprimida o espejada)
     ya presentada en otro siniestro, usando hash perceptual, el identificador único que
     algunas cámaras graban en cada foto y un registro compartido.
  7. El mismo teléfono (número de serie de la cámara) en siniestros de distintos asegurados.
  8. Dentro del mismo siniestro: la misma foto presentada dos veces (o espejada, para
     simular el otro lado del auto) y fotos de varios teléfonos distintos.
  9. Pistas del archivo: tamaño típico de imágenes generadas por IA, nombre de archivo de
     edición y, en el portal, fecha del archivo posterior a la fecha de la foto.

Cada hallazgo cita el evento de la foto (y de la declaración cuando corresponde),
de modo que el asistente verificable y el informe funcionan igual que en incidentes.

Límites: ninguna de estas señales prueba fraude por sí sola, y la ausencia de
señales no prueba autenticidad. Los metadatos se pueden falsificar; las marcas de IA
se pueden quitar. El resultado es una priorización para revisión humana.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from evidex.core.storage import serialized, atomic_json

from PIL import Image

try:                                    # fotos HEIC de iPhone (opcional: pip install pillow-heif)
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

from evidex.core.detections import Finding
from evidex.forensics.chile import norm_plate, plate_format


def chile_plate_ok(p) -> bool:
    return bool(plate_format(p or ""))


def _fmt_plate(p: str) -> str:
    return f"{p[:4]}·{p[4:]}" if plate_format(p) == "nueva" else f"{p[:2]}·{p[2:]}"
from evidex.forensics import image_content
from evidex.forensics import deep_meta, derived, ocr
from evidex.forensics import photo_metadata as photo_forensics

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".heic"}
EDITORS = ["photoshop", "lightroom", "gimp", "snapseed", "picsart", "facetune", "pixlr",
           "canva", "affinity", "photopea", "meitu", "remini", "fotor", "polarr"]
AI_MARKERS = [b"trainedAlgorithmicMedia", b"Midjourney", b"DALL-E", b"DALL\xc2\xb7E",
              b"Stable Diffusion", b"stable-diffusion", b"Adobe Firefly", b"ComfyUI", b"NovelAI"]
AI_TEXT_KEYS = ("parameters", "prompt", "workflow")

WHATSAPP_NAME = re.compile(r"(whatsapp[ _]image|IMG-\d{8}-WA\d+)", re.I)
EDIT_NAME = re.compile(r"(edit|retoc|photoshop|snapseed|picsart|lightroom|facetune|remini|[-_ ]copia|[-_ ]copy\b|\(\d\)\.)", re.I)
# tamaños exactos que entregan los generadores de imágenes (SDXL, DALL·E, GPT-image, Midjourney, Flux);
# no se incluyen tamaños 4:3 como 1024×768, que también usan cámaras antiguas
_AI = [(512, 512), (768, 768), (1024, 1024), (2048, 2048), (1152, 896), (1216, 832), (1344, 768), (1536, 640),
       (1792, 1024), (1536, 1024), (1456, 816), (1232, 928), (1312, 736), (1440, 816), (1344, 896), (1248, 832)]
AI_SIZES = {s for w, h in _AI for s in ((w, h), (h, w))}
SAME_CLAIM_DUP = 6          # bits: dos fotos del mismo siniestro casi idénticas
SAVED_AFTER = timedelta(days=1)
DUP_MAX_DISTANCE = 10       # bits de diferencia en el hash perceptual (de 64); valor usual 8-12
GPS_WARN_KM, GPS_ALERT_KM = 5, 50
BEFORE_TOLERANCE = timedelta(hours=2)
LATE_AFTER = timedelta(days=7)


# ---- metadatos ------------------------------------------------------------
def dhash_variants(img: Image.Image) -> dict:
    """Hash de la foto espejada: quien reutiliza una foto a veces la invierte para que parezca otra."""
    from PIL import ImageOps
    return {"dhash_flip": dhash(ImageOps.mirror(img))}


def dhash(img: Image.Image, size: int = 8) -> str:
    """Hash perceptual por diferencias: resiste recorte leve, cambio de tamaño y recompresión."""
    g = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    px = list(g.tobytes())  # un byte por píxel en modo "L"
    bits = 0
    for r in range(size):
        for c in range(size):
            bits = (bits << 1) | int(px[r * (size + 1) + c] > px[r * (size + 1) + c + 1])
    return f"{bits:016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _exif_date(value) -> datetime | None:
    try:
        return datetime.strptime(str(value).strip("\x00 "), "%Y:%m:%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def _gps(ifd: dict) -> tuple[float, float] | None:
    try:
        def deg(v):
            d, m, s = (float(x) for x in v)
            return d + m / 60 + s / 3600
        lat, lon = deg(ifd[2]), deg(ifd[4])
        return (-lat if ifd.get(1) == "S" else lat, -lon if ifd.get(3) == "W" else lon)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def photo_metadata(path: Path, name: str | None = None, content: bool = True) -> dict:
    raw = Path(path).read_bytes()
    with Image.open(path) as img:
        exif = img.getexif()
        sub, gps = exif.get_ifd(0x8769), exif.get_ifd(0x8825)
        taken = _exif_date(sub.get(0x9003) or exif.get(0x0132))
        text = {k: v[:300] for k, v in (img.info or {}).items() if isinstance(v, str)}
        meta = {
            "format": img.format, "width": img.width, "height": img.height,
            "make": exif.get(0x010F), "model": exif.get(0x0110), "software": exif.get(0x0131),
            "taken": taken.isoformat() if taken else None, "gps": _gps(gps),
            "has_exif": len(exif) > 0, "text_keys": sorted(text), "dhash": dhash(img), **dhash_variants(img),
            "forensics": photo_forensics.inspect(img, raw[:4_000_000], name or Path(path).name, dhash),
        }
    try:                       # todas las secciones y metadatos del archivo (Samsung, Apple, Google, XMP, C2PA...)
        meta["deep"] = deep_meta.compact(deep_meta.read_all(path, raw))
    except Exception as ex:
        meta["deep"] = {"error": type(ex).__name__}
    meta["ai_markers"] = sorted({m.decode("utf-8", "ignore") for m in AI_MARKERS if m in raw[:4_000_000]})
    if content:
        try:
            meta["content"] = image_content.analyze_image(path)
        except Exception as ex:  # una imagen rara no debe impedir el resto del análisis
            meta["content"] = {"error": type(ex).__name__}
    return meta


# ---- análisis ---------------------------------------------------------------
@dataclass
class Photo:
    digest: str
    name: str
    meta: dict
    ts: str  # fecha de la foto o, si no tiene, hora de recepción
    path: Path | None = None  # archivo, para comparar fotos entre sí (recortes)

    @property
    def ev(self) -> str:
        return f"{self.digest[:8]}:1"


DATE_TOLERANCE = timedelta(hours=14)     # diferencias de zona horaria posibles entre una fecha local y una UTC


def _parse_any_date(v: str) -> datetime | None:
    v = str(v).strip()
    for fmt, n in (("%Y:%m:%d %H:%M:%S", 19), ("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d %H:%M:%S", 19), ("%Y%m%d %H%M%S", 15)):
        try:
            return datetime.strptime(v[:n], fmt)
        except ValueError:
            continue
    return None


def _date_conflict(dates: dict, taken: str | None) -> str | None:
    """Compara la fecha de la foto (EXIF) con las demás fechas de captura que guarda el archivo.
    Solo fechas de captura: las de modificación o firma pueden ser posteriores sin problema."""
    base = _parse_any_date(taken) if taken else None
    if not base:
        return None
    capture_keys = ("Samsung: hora UTC", "XMP xmp:CreateDate", "XMP photoshop:DateCreated", "XMP exif:DateTimeOriginal",
                    "IPTC: creación", "XMP Iptc4xmpCore:DateCreated")
    diffs = []
    for k in capture_keys:
        other = _parse_any_date(dates.get(k, "")) if dates.get(k) else None
        if other and abs(other - base) > DATE_TOLERANCE:
            diffs.append(f"la foto dice {_fmt(base)} y «{k}» dice {_fmt(other)}")
    return "; ".join(diffs) or None


def _fmt(dt: datetime) -> str:
    return dt.strftime("%d-%m-%Y %H:%M")


def analyze(decl: dict, decl_ev: str, photos: list[Photo], registry: list[dict]) -> list[Finding]:
    out: list[Finding] = []
    t0 = datetime.fromisoformat(decl["fecha_siniestro"])
    place = (decl["lat"], decl["lon"]) if decl.get("lat") is not None else None

    for p in photos:
        m, cite = p.meta, [p.ev]
        if "error" in m:
            out.append(Finding("unreadable", "baja", f"No se pudo analizar {p.name}",
                               f"El archivo {p.name} no se pudo abrir ({m['error']}) y debe revisarse manualmente.", cite, p.ts))
            continue

        ai = m["ai_markers"] + [k for k in AI_TEXT_KEYS if k in m["text_keys"]]
        deep = m.get("deep") or {}
        deep_ai = deep.get("ai") or []
        if ai:
            detail = (" Lo que dice el archivo: " + "; ".join(deep_ai) + ".") if deep_ai else ""
            out.append(Finding("ai_generated", "alta", f"Posible imagen generada por IA ({p.name})",
                               f"La imagen {p.name} contiene marcas de herramientas de generación por IA ({', '.join(ai)})."
                               + detail, cite, p.ts))
        elif deep_ai:
            out.append(Finding("ai_edited", "alta", f"Editada con IA según el propio archivo ({p.name})",
                               f"El archivo {p.name} declara que se usó inteligencia artificial: " + "; ".join(deep_ai)
                               + ". Lo anota el teléfono o la app al guardar la imagen; no depende de cuánto se haya "
                               "cambiado, así que también aparece cuando la edición es pequeña.", cite, p.ts))
        if (deep.get("flags") or {}).get("ai_watermark_removed"):
            out.append(Finding("ai_watermark_removed", "alta", f"Se quitó la marca de IA ({p.name})",
                               f"El editor de la galería de Samsung registró que en {p.name} se quitó la marca visible "
                               "que indica que la imagen fue editada con IA.", cite, p.ts))
        edits = [e for e in deep.get("edits") or [] if "«converted»" not in e]
        if edits:
            out.append(Finding("phone_edit", "media", f"Editada después de tomarla ({p.name})",
                               f"El archivo {p.name} trae el registro de estas ediciones: " + "; ".join(edits) + ".",
                               cite, p.ts))
        conflict = _date_conflict(deep.get("dates") or {}, m.get("taken"))
        if conflict:
            out.append(Finding("meta_dates_conflict", "media", f"Fechas internas que no coinciden ({p.name})",
                               f"El archivo {p.name} guarda fechas distintas en distintas secciones: {conflict}. "
                               "Cuando se cambia la fecha de una foto con una app, suele cambiarse solo una de ellas.",
                               cite, p.ts))

        w, h = m.get("width") or 0, m.get("height") or 0
        if not ai and not m.get("make") and (w, h) in AI_SIZES:
            out.append(Finding("ai_dimensions", "media", f"Tamaño típico de imagen generada por IA ({p.name})",
                               f"La imagen {p.name} mide {w}×{h} y no trae datos de cámara. Ese tamaño es el que usan "
                               "algunos generadores de IA, pero también puede resultar de un recorte o exportación legítimos.", cite, p.ts))
        label = derived.ai_label(((m.get("content") or {}).get("ocr") or {}).get("text") or "")
        if label:
            out.append(Finding("ai_label_visible", "alta", f"La imagen dice que fue hecha con IA ({p.name})",
                               f"En la foto {p.name} se lee el texto «{label}». Esa marca la estampan las apps "
                               "(Samsung, Google, Meta y otras) cuando la imagen se generó o se editó con inteligencia "
                               "artificial: lo que muestra no es una foto sin modificar.", cite, p.ts))
        ratio = derived.odd_ratio(w, h)
        if ratio and not ai and not m.get("make") and (w, h) not in AI_SIZES:
            out.append(Finding("odd_ratio", "baja", f"Proporción que no es de cámara ({p.name})",
                               f"La foto {p.name} mide {w}×{h} (proporción {str(ratio).replace('.', ',')} a 1). Los teléfonos guardan las fotos en "
                               "proporciones fijas (4:3, 16:9, 1:1...) y WhatsApp las mantiene, así que esta imagen se "
                               "recortó a mano o se generó. Recortar puede ser inocente, pero también sirve para sacar "
                               "marcas, fechas o partes que delatan otra cosa: pida la foto completa.", cite, p.ts))
        if EDIT_NAME.search(p.name) and not WHATSAPP_NAME.search(p.name):
            out.append(Finding("edit_filename", "baja", f"El nombre del archivo sugiere edición ({p.name})",
                               f"El nombre {p.name} es el que dejan las apps de edición o una copia del archivo. "
                               "Conviene pedir la foto original.", cite, p.ts))
        lm = (m.get("portal") or {}).get("last_modified")
        if lm and m.get("taken"):
            saved = datetime.fromtimestamp(lm / 1000)
            gap = saved - datetime.fromisoformat(m["taken"])
            # solo se usa en este sentido: iPhone y algunos Android informan como fecha del archivo el momento
            # en que se elige en la galería, así que un archivo "más nuevo" que la foto es normal
            if gap < -SAVED_AFTER:
                out.append(Finding("saved_before_taken", "alta", f"La fecha de la foto es posterior a su archivo ({p.name})",
                                   f"El archivo {p.name} existía en el teléfono el {_fmt(saved)}, pero la foto dice haberse "
                                   f"tomado después, el {_fmt(datetime.fromisoformat(m['taken']))}. Es imposible: la fecha "
                                   "interna de la foto se cambió.", cite, p.ts))

        sw = (m.get("software") or "").lower()
        if any(e in sw for e in EDITORS):
            out.append(Finding("edited", "alta", f"Foto editada ({p.name})",
                               f"Los metadatos de {p.name} indican que pasó por un editor de imágenes ({m['software']}).",
                               cite, p.ts))

        if m.get("secure_capture"):
            from evidex.portal.links import findings_for
            out += findings_for(p, decl, cite)
        elif not m["has_exif"] and not ai:
            if m.get("portal"):
                out.append(Finding("no_metadata", "media", f"Foto subida sin fecha ni ubicación ({p.name})",
                                   f"La foto {p.name} la subió el asegurado desde su galería, pero no trae fecha, cámara "
                                   "ni ubicación. Es típico de una foto que antes pasó por WhatsApp, de una captura de "
                                   "pantalla o de una foto descargada: no se puede verificar cuándo ni dónde se tomó.",
                                   cite, p.ts))
            elif WHATSAPP_NAME.search(p.name):
                out.append(Finding("no_metadata", "baja", f"Foto recibida por WhatsApp, sin metadatos ({p.name})",
                                   f"La foto {p.name} llegó por WhatsApp, que borra la fecha, la cámara y la ubicación de "
                                   "toda imagen enviada. No se puede verificar cuándo ni dónde se tomó. Pida al asegurado "
                                   "el archivo original, enviado por WhatsApp como Documento o por correo.",
                                   cite, p.ts))
            else:
                out.append(Finding("no_metadata", "media", f"Foto sin fecha, cámara ni ubicación ({p.name})",
                                   f"La foto {p.name} no trae los datos que todo celular guarda al tomar una foto: no dice "
                                   "cuándo se tomó, con qué teléfono ni dónde. Por eso no se puede comprobar que sea de "
                                   "este choque. Lo más común es que se haya reenviado por WhatsApp o redes sociales "
                                   "(que borran esos datos), que sea una captura de pantalla o que se haya descargado.",
                                   cite, p.ts))

        if m.get("taken"):
            taken = datetime.fromisoformat(m["taken"])
            delta = taken - t0
            if delta < -BEFORE_TOLERANCE:
                out.append(Finding("taken_before", "alta", f"Foto anterior al siniestro ({p.name})",
                                   f"La foto {p.name} se tomó el {_fmt(taken)}, {abs(delta.days) or 'menos de 1'} día(s) "
                                   f"antes de la fecha declarada del siniestro ({_fmt(t0)}).",
                                   cite + [decl_ev], p.ts))
            elif delta > LATE_AFTER:
                out.append(Finding("taken_late", "media", f"Foto muy posterior al siniestro ({p.name})",
                                   f"La foto {p.name} se tomó {delta.days} días después del siniestro declarado.",
                                   cite + [decl_ev], p.ts))

        received = None
        if m.get("received"):
            received = datetime.fromisoformat(m["received"].rstrip("Z")).replace(tzinfo=None)
        for rule, sev, title, text in ([] if m.get("secure_capture") else photo_forensics.signals(m, received, hamming)):
            if rule == "resized_after_capture" and any(e.startswith("Recorte en la galería") for e in edits):
                continue                            # ya se informa con el detalle del recorte en "Editada después de tomarla"
            out.append(Finding(rule, sev, f"{title} ({p.name})", f"Foto {p.name}: {text}", cite, p.ts))

        out += content_findings(p, decl, place, cite)

        if place and m.get("gps"):
            km = km_between(place, tuple(m["gps"]))
            if km > GPS_WARN_KM:
                sev = "alta" if km > GPS_ALERT_KM else "media"
                out.append(Finding("gps_mismatch", sev, f"Ubicación no coincide ({p.name})",
                                   f"La foto {p.name} se tomó a {km:.0f} km del lugar declarado ({decl.get('lugar', '')}).",
                                   cite + [decl_ev], p.ts))

        out += registry_findings(p, decl, registry, cite)

    out += photo_set_findings(photos)
    for f in out:
        f.category = "Fotos"
    out.sort(key=lambda f: ({"alta": 0, "media": 1, "baja": 2}[f.severity], f.first_ts))
    return out


def _ruts_by_claim(registry: list[dict]) -> dict[str, str]:
    return {r["claim"]: re.sub(r"[^0-9kK]", "", r.get("rut") or "").upper() for r in registry if r.get("type") == "claim"}


def registry_findings(p: "Photo", decl: dict, registry: list[dict], cite) -> list[Finding]:
    """La misma foto (aunque esté espejada o editada) o el mismo teléfono en otro siniestro."""
    m, out = p.meta, []
    fx = m.get("forensics") or {}
    uid, serial = fx.get("image_uid"), fx.get("serial")
    rut = re.sub(r"[^0-9kK]", "", decl.get("rut") or "").upper()
    ruts = None
    reused = device = False
    for r in registry:
        if r.get("type", "photo") != "photo" or r["claim"] == decl["numero"]:
            continue
        if not reused:
            how = None
            if r["sha256"] == p.digest:
                how = "idéntica"
            elif r.get("dhash") and hamming(r["dhash"], m["dhash"]) <= DUP_MAX_DISTANCE:
                how = "casi idéntica (recortada, redimensionada o recomprimida)"
            elif r.get("dhash") and m.get("dhash_flip") and hamming(r["dhash"], m["dhash_flip"]) <= DUP_MAX_DISTANCE:
                how = "la misma foto, pero espejada (invertida de izquierda a derecha) para que parezca otra"
            elif uid and r.get("uid") == uid:
                how = ("la misma toma: ambas llevan el mismo identificador único que la cámara graba en cada foto, "
                       "aunque la imagen se haya editado")
            if how:
                ai_note = ""
                if r.get("ai") and not _ai_evidence(p):
                    ai_note = (f" Además, esa foto declaraba uso de inteligencia artificial ({r['ai']}): esta copia "
                               "llegó sin esas marcas.")
                out.append(Finding("reused_photo", "alta", f"Foto ya usada en otro siniestro ({p.name})",
                                   f"La foto {p.name} es {how}, igual a la foto {r['photo']} del siniestro {r['claim']}."
                                   + ai_note, cite, p.ts))
                if ai_note:
                    out.append(Finding("copy_of_ai_photo", "alta", f"Copia de una foto editada con IA ({p.name})",
                                       f"La foto {p.name} es {how} de la foto {r['photo']} del siniestro {r['claim']}, "
                                       f"que declaraba uso de inteligencia artificial: {r['ai']}. La copia llegó sin "
                                       "esas marcas.", cite, p.ts))
                reused = True
        if not device and serial and r.get("serial") == serial:
            ruts = ruts if ruts is not None else _ruts_by_claim(registry)
            other = ruts.get(r["claim"], "")
            if rut and other and other != rut:
                out.append(Finding("same_device_other_claim", "alta", f"Mismo teléfono en el siniestro de otro asegurado ({p.name})",
                                   f"La foto {p.name} se tomó con la cámara número de serie {serial}, la misma que tomó la "
                                   f"foto {r['photo']} del siniestro {r['claim']}, de otro asegurado. Una misma persona "
                                   "fotografiando siniestros de distintos asegurados es una señal típica de redes de fraude "
                                   "(talleres, tramitadores).", cite, p.ts))
                device = True
    return out


def photo_set_findings(photos: list["Photo"]) -> list[Finding]:
    """Revisa las fotos del siniestro en conjunto."""
    out: list[Finding] = []
    ok = [p for p in photos if "error" not in p.meta and p.meta.get("dhash")]
    # la misma foto presentada dos veces (con otro nombre) o espejada para simular el otro lado
    seen = set()
    crops = _crop_pairs(ok)
    for a, b, rel in crops:
        base, part = (a, b) if rel["base"] == "a" else (b, a)
        change = rel.get("change")
        if change:
            seen.add((a.digest, b.digest))
            how = "es la foto" if rel["same"] else "es un recorte de la foto"
            out.append(Finding("changed_between_versions", "alta", f"Zona cambiada entre dos versiones ({part.name})",
                               f"La foto {part.name} {how} {base.name}, pero una zona {change['where']} no es igual: "
                               "algo se borró, se agregó o se cambió (por ejemplo con el borrador mágico o la edición "
                               "con IA del teléfono). Compare las dos fotos en esa zona.", [base.ev, part.ev], part.ts))
        if rel["same"]:
            if (copy := _copy_of_ai(a, b, "es la misma imagen que la foto")):
                seen.add((a.digest, b.digest))
                out.append(copy)
            continue
        seen.add((a.digest, b.digest))
        sides = ", ".join(f"{round(v * 100)}% por {s}" for s, v in rel["cut"].items())
        label = _ai_label(base)
        if label and not _ai_label(part):
            out.append(Finding("ai_mark_cropped", "alta", f"Foto recortada para sacar la marca de IA ({part.name})",
                               f"La foto {part.name} es la foto {base.name} recortada (se quitó {sides}). La foto completa "
                               f"tiene el texto «{label}», y la recortada ya no lo muestra: se recortó para que no se note "
                               "que la imagen fue generada o editada con IA.", [base.ev, part.ev], part.ts))
        elif (copy := _copy_of_ai(base, part, f"es un recorte (se quitó {sides}) de la foto")):
            out.append(copy)
        else:
            out.append(Finding("cropped_in_claim", "media", f"Una foto es recorte de otra ({part.name})",
                               f"La foto {part.name} es la foto {base.name} recortada (se quitó {sides}). Si se presentaron "
                               "como fotos distintas, o si la parte quitada mostraba algo (una marca, una fecha, otro "
                               "vehículo), hay que preguntar por qué.", [base.ev, part.ev], part.ts))
    for i, a in enumerate(ok):
        for b in ok[i + 1:]:
            if a.digest == b.digest or (a.digest, b.digest) in seen:
                continue
            flip = b.meta.get("dhash_flip") and hamming(a.meta["dhash"], b.meta["dhash_flip"]) <= SAME_CLAIM_DUP \
                and hamming(a.meta["dhash"], b.meta["dhash"]) > SAME_CLAIM_DUP
            same = hamming(a.meta["dhash"], b.meta["dhash"]) <= SAME_CLAIM_DUP
            if not (flip or same):
                continue
            seen.add((a.digest, b.digest))
            if flip:
                out.append(Finding("mirrored_in_claim", "alta", f"Foto espejada presentada como otra ({b.name})",
                                   f"La foto {b.name} es la foto {a.name} invertida de izquierda a derecha. Se usa para "
                                   "mostrar el mismo daño como si fuera del otro costado del vehículo.",
                                   [a.ev, b.ev], b.ts))
            elif (copy := _copy_of_ai(a, b, "es prácticamente la misma imagen que la foto")):
                out.append(copy)
            else:
                out.append(Finding("duplicate_in_claim", "media", f"La misma foto dos veces ({b.name})",
                                   f"Las fotos {a.name} y {b.name} son prácticamente la misma imagen. Puede ser una ráfaga, "
                                   "pero si se presentaron como fotos de daños distintos, hay que preguntar.",
                                   [a.ev, b.ev], b.ts))
    # fotos de varios teléfonos: el asegurado dice haber fotografiado su propio choque
    devices: dict[str, list] = {}
    for p in ok:
        if p.meta.get("make") and not p.meta.get("secure_capture"):
            key = " ".join(filter(None, [str(p.meta["make"]).strip(), str(p.meta.get("model") or "").strip()]))
            devices.setdefault(key, []).append(p)
    if len(devices) >= 2:
        detail = "; ".join(f"{k}: {', '.join(x.name for x in v)}" for k, v in devices.items())
        out.append(Finding("multiple_devices", "media", f"Fotos tomadas con {len(devices)} teléfonos distintos",
                           f"Las fotos del siniestro vienen de cámaras distintas ({detail}). Puede ser normal (el otro "
                           "conductor, la grúa), pero si el asegurado dice haberlas tomado él, alguna puede ser de otro "
                           "evento.", [x.ev for v in devices.values() for x in v],
                           min(x.ts for v in devices.values() for x in v)))
    return out


CROP_MAX_PHOTOS = 20   # con más fotos solo se comparan los pares parecidos (cada par toma ~0,1 s)


CONTENT_VERSION = 2        # súbalo si cambia el análisis de píxeles o de C2PA: se recalcula la caché por foto
PAIRS_CACHE = "analisis_pares.json"
PAIRS_VERSION = 1          # súbalo si cambia cómo se comparan las fotos


def _plain(v):
    """Números y booleanos de numpy como tipos normales, para guardarlos en JSON."""
    if hasattr(v, "item"):
        return v.item()
    raise TypeError(type(v).__name__)


def _pairs_cache(files: list["Photo"]) -> tuple[Path | None, dict]:
    """Comparaciones ya hechas entre fotos del caso: no cambian mientras no cambien las fotos."""
    folder = Path(files[0].path).parent if files else None
    if folder is None or folder.name != "evidence":             # solo dentro de un caso
        return None, {}
    path = folder.parent / PAIRS_CACHE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return path, data.get("pairs", {}) if data.get("version") == PAIRS_VERSION else {}
    except (OSError, ValueError):
        return path, {}


def _crop_pairs(photos: list["Photo"]) -> list[tuple]:
    """Pares de fotos (a, b, relación) que son la misma toma: recortada o con el mismo encuadre.
    La relación incluye la zona cambiada entre las dos versiones ("change"), si la hay."""
    files = [p for p in photos if p.path and Path(p.path).exists()]
    path, cache = _pairs_cache(files)
    dirty, out = False, []
    for i, a in enumerate(files):
        for b in files[i + 1:]:
            if a.digest == b.digest:
                continue
            if len(files) > CROP_MAX_PHOTOS and hamming(a.meta["dhash"], b.meta["dhash"]) > 20:
                continue
            key = f"{a.digest}:{b.digest}"
            if key in cache:
                rel = cache[key]
            else:
                rel = derived.relation(a.path, b.path)
                if rel:
                    base, part = (a, b) if rel["base"] == "a" else (b, a)
                    try:
                        rel["change"] = derived.changed_region(base.path, part.path, rel)
                    except Exception:
                        rel["change"] = None
                cache[key], dirty = rel, True
            if rel:
                out.append((a, b, rel))
    if dirty and path is not None:
        try:
            path.write_text(json.dumps({"version": PAIRS_VERSION, "pairs": cache}, default=_plain), encoding="utf-8")
        except (OSError, TypeError, ValueError):
            pass                        # la caché es solo para ir más rápido: si falla, el análisis sigue igual
    return out


def _ai_label(p: "Photo") -> str | None:
    """La marca visible «Contenido generado por IA» leída en la imagen."""
    return derived.ai_label(((p.meta.get("content") or {}).get("ocr") or {}).get("text") or "")


def _ai_evidence(p: "Photo") -> str | None:
    """Qué muestra que la foto se hizo o editó con IA: marca visible, marcas en el archivo o lo que declara
    el teléfono o la app (Galaxy AI, C2PA, XMP)."""
    m = p.meta
    if label := _ai_label(p):
        return f"el texto «{label}»"
    if m.get("ai_markers"):
        return f"marcas de IA en el archivo ({', '.join(m['ai_markers'])})"
    deep_ai = (m.get("deep") or {}).get("ai") or []
    if deep_ai:
        return "; ".join(deep_ai[:2])
    return None


def _copy_of_ai(a: "Photo", b: "Photo", how: str) -> "Finding | None":
    """Si una de dos fotos que son la misma toma tiene marcas de IA y la otra no, la otra es una copia que
    perdió las marcas (WhatsApp, captura de pantalla, recorte): hereda la alerta."""
    ea, eb = _ai_evidence(a), _ai_evidence(b)
    if bool(ea) == bool(eb):
        return None
    src, copy, mark = (a, b, ea) if ea else (b, a, eb)
    return Finding("copy_of_ai_photo", "alta", f"Copia de una foto editada con IA ({copy.name})",
                   f"La foto {copy.name} {how} {src.name}, que declara uso de inteligencia artificial: {mark}. "
                   f"La copia llegó sin esas marcas (WhatsApp, redes sociales o una captura las borran), pero la "
                   f"imagen es la misma.", [src.ev, copy.ev], copy.ts)


def content_findings(p: "Photo", decl: dict, place, cite) -> list[Finding]:
    """Hallazgos del análisis de píxeles (doble compresión, zonas pegadas, clonado, luz, C2PA)."""
    m, out = p.meta, []
    c = m.get("content") or {}
    fx = m.get("forensics") or {}
    camera_original = bool(m.get("make") and fx.get("exposure")) and not WHATSAPP_NAME.search(p.name)
    g = c.get("ghost") or {}
    if g.get("region"):
        out.append(Finding("pasted_region", "alta", f"Zona de la foto agregada después ({p.name})",
                           f"Una zona de {p.name} (marcada en rojo en la revisión de la foto) no tiene la huella de "
                           f"compresión que tiene el resto de la imagen: el resto se guardó antes con calidad "
                           f"~{g['q_first']} y esa zona no. Es la huella típica de pegar un elemento (daño, patente, "
                           "objeto) desde otra imagen.", cite, p.ts))
    elif g.get("q_first") and camera_original:
        out.append(Finding("recompressed", "media", f"Foto guardada de nuevo después de la cámara ({p.name})",
                           f"La foto {p.name} dice venir directo de la cámara, pero tiene huella de una compresión anterior "
                           f"(calidad ~{g['q_first']}, luego ~{g['q_final']}). Se abrió y volvió a guardar, por ejemplo "
                           "en un editor.", cite, p.ts))
    nz = (c.get("noise") or {}).get("region")
    if nz and not g.get("region"):
        out.append(Finding("noise_inconsistent", "media", f"Zona con grano distinto al resto ({p.name})",
                           f"Una zona de {p.name} (marcada en morado en la revisión de la foto) tiene {nz['kind']} grano "
                           f"de sensor que el resto de la imagen (unas {nz['ratio']} veces). Toda la foto sale del mismo "
                           "sensor, así que una zona con otro grano puede venir de otra imagen o estar retocada.",
                           cite, p.ts))
    cl = c.get("clone") or {}
    if cl.get("src"):
        out.append(Finding("cloned_region", "alta", f"Parte de la imagen duplicada ({p.name})",
                           f"Una zona de {p.name} aparece copiada en otro lugar de la misma foto ({cl['matches']} "
                           "coincidencias con el mismo desplazamiento). Se usa para agrandar un daño o tapar algo.",
                           cite, p.ts))
    cap = m.get("secure_capture") or {}
    when = cap.get("server_time") or m.get("taken")
    loc = tuple(m["gps"]) if m.get("gps") else place
    if when and loc and c.get("sky_day"):
        local = datetime.fromisoformat(when[:19])
        utc = (datetime.fromisoformat(cap["server_utc"]) if cap.get("server_utc")
               else local - image_content.chile_offset(local))
        elev = image_content.solar_elevation(loc[0], loc[1], utc)
        if elev < -6:
            out.append(Finding("daylight_at_night", "media", f"Foto de día con hora de noche ({p.name})",
                               f"La foto {p.name} muestra cielo de día, pero su fecha ({_fmt(local)}) corresponde a la noche en ese "
                               f"lugar (el sol estaba {abs(elev):.0f}° bajo el horizonte). La fecha de la foto no es "
                               "la real.", cite, p.ts))
    read = [x for x in ((c.get("ocr") or {}).get("plates") or [])]
    declared = norm_plate(decl.get("patente"))
    if read and declared and declared not in read:
        is_plate_shot = "patente" in p.name.lower() or (m.get("secure_capture") or {}).get("shot") == "patente"
        shown = ", ".join(_fmt_plate(x) for x in read)
        out.append(Finding("plate_photo_mismatch", "alta" if is_plate_shot else "media",
                           f"Aparece otra patente en la foto ({p.name})",
                           f"Evidex leyó en la foto {p.name} la patente {shown}, que no es la del vehículo asegurado "
                           f"({decl.get('patente')}). "
                           + ("Esta es la foto que debía mostrar la patente del vehículo asegurado, así que probablemente "
                              "muestra otro auto." if is_plate_shot else
                              "Puede ser el otro auto del choque o uno que aparece de fondo; si la foto debía mostrar el "
                              "vehículo asegurado, es una foto de otro auto.")
                           + ("" if chile_plate_ok(decl.get("patente")) else
                              f" Ojo: la patente declarada ({decl.get('patente')}) tampoco tiene un formato válido; "
                              "revísela en el padrón."),
                           cite, p.ts))
    cp = c.get("c2pa")
    if cp and cp.get("valid") is False:
        out.append(Finding("c2pa_invalid", "alta", f"Firma de autenticidad rota ({p.name})",
                           f"La foto {p.name} tiene credenciales de contenido C2PA (firma de la cámara o de la app), pero la "
                           f"credencial no es válida ({cp.get('state') or 'error'}). Esto no identifica por sí solo una edición de píxeles ni su causa.",
                           cite, p.ts))
    return out


SEVERITY_POINTS = {"alta": 25, "media": 10, "baja": 3}


def risk_score(findings: list[Finding]) -> int:
    """Puntaje 0-100 para ordenar la cola de trabajo. No es una probabilidad de fraude."""
    return min(100, sum(SEVERITY_POINTS[f.severity] for f in findings))


def recommendation(findings: list[Finding]) -> tuple[str, str]:
    if any(f.severity == "alta" for f in findings):
        return "Derivar a la unidad de investigación de fraude", "bad"
    if any(f.severity == "media" for f in findings):
        return "Revisión manual del liquidador", "warn"
    if findings:  # solo observaciones de severidad baja
        return "Sin alertas relevantes: continuar el flujo normal", "ok"
    return "Sin alertas: continuar el flujo normal", "ok"


# ---- registro compartido entre siniestros --------------------------------------
_REGISTRY_CACHE: dict[str, tuple[int, list[dict]]] = {}


@serialized(lambda path, *a, **kw: path)
def load_registry(path: Path | None) -> list[dict]:
    """Lee el registro compartido. Como solo se le agregan líneas al final, se guarda en memoria
    y en cada llamada se leen solo las líneas nuevas (importar miles de siniestros sigue siendo rápido)."""
    if not path or not Path(path).exists():
        return []
    key, size = str(Path(path).resolve()), Path(path).stat().st_size
    cached = _REGISTRY_CACHE.get(key)
    if cached and cached[0] == size:
        return cached[1]
    if cached and cached[0] < size:
        with open(path, "rb") as f:
            f.seek(cached[0])
            new = f.read().decode("utf-8")
        rows = cached[1] + [json.loads(x) for x in new.splitlines() if x.strip()]
    else:
        rows = [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
    _REGISTRY_CACHE[key] = (size, rows)
    return rows


@serialized(lambda path, *a, **kw: path)
def update_registry(path: Path, claim: str, photos: list[Photo], docs=(), decl: dict | None = None,
                    level: str | None = None) -> None:
    """Agrega al registro las fotos, documentos y datos del siniestro (sin duplicar)."""
    reg = load_registry(path)
    known = {(r.get("type", "photo"), r["claim"], r.get("sha256")) for r in reg}
    with_ai = {(r["claim"], r.get("sha256")) for r in reg if r.get("type", "photo") == "photo" and r.get("ai")}
    lines = []
    for p in photos:
        ai = _ai_evidence(p) if "dhash" in p.meta else None
        # se agrega la foto nueva, o se vuelve a anotar una ya registrada si ahora se sabe que tiene marcas de IA
        if "dhash" in p.meta and (("photo", claim, p.digest) not in known or (ai and (claim, p.digest) not in with_ai)):
            fx = p.meta.get("forensics") or {}
            row = {"type": "photo", "claim": claim, "photo": p.name, "sha256": p.digest, "dhash": p.meta["dhash"]}
            row.update({k: v for k, v in (("uid", fx.get("image_uid")), ("serial", fx.get("serial")), ("ai", ai)) if v})
            lines.append(row)
    for d in docs:
        if ("doc", claim, d.digest) not in known:
            lines.append({"type": "doc", "claim": claim, "name": d.name, "sha256": d.digest})
    if decl is not None:
        from evidex.forensics.network import claim_record
        rec = claim_record(decl, level)
        last = next((r for r in reversed(reg) if r.get("type") == "claim" and r["claim"] == claim), None)
        if last is None or {k: v for k, v in last.items()} != rec:
            lines.append(rec)
    if lines:
        with Path(path).open("a", encoding="utf-8") as f:
            for x in lines:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")


def registry_claims(registry: list[dict]) -> dict[str, dict]:
    """Última ficha registrada de cada siniestro."""
    out: dict[str, dict] = {}
    for r in registry:
        if r.get("type") == "claim":
            out[r["claim"]] = r
    return out


# ---- carga del caso ----------------------------------------------------------
def read_declaration(path: Path) -> dict:
    """Lee la declaración en UTF-8 y, si falla, en la codificación clásica de Windows.

    El Bloc de notas y Excel en Windows a veces guardan en cp1252 ("ANSI"). Se acepta igual,
    porque la evidencia se custodia byte a byte y no se modifica.
    """
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return json.loads(raw.decode(enc))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"no se pudo leer {path}: codificación desconocida")


def load_case(case, timeline) -> tuple[dict, str, list[Photo]]:
    """Lee declaración y fotos del caso y las registra como eventos citables."""
    decl, decl_ev, photos = None, None, []
    cache_path = case.root / "analisis_imagen.json"   # el análisis de píxeles es lento: se guarda por hash
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    if not isinstance(cache, dict) or cache.get("_schema") != 2:
        cache = {"_schema": 2}
    dirty = False
    for e in case.active_evidence():
        path, name = case.evidence_dir / e["subject"], e["data"]["original_name"]
        ev = f"{e['subject'][:8]}:1"
        if e["data"].get("note") == "declaracion":
            decl, decl_ev = read_declaration(path), ev
            timeline.add_event(ev, decl["fecha_siniestro"], name, "declaración", None, decl.get("asegurado"),
                               f"Siniestro {decl['numero']} declarado en {decl.get('lugar', '')}: {decl.get('descripcion', '')}")
        elif Path(name).suffix.lower() in IMAGE_EXT and e["data"].get("note") != "documento":
            try:
                meta = photo_metadata(path, name, content=False)
                meta["received"] = e["ts"]
                if (cache.get(e["subject"]) or {}).get("_v") != CONTENT_VERSION:   # sin calcular o de una versión anterior
                    try:
                        cache[e["subject"]] = image_content.analyze_image(path)
                    except Exception as ex:
                        cache[e["subject"]] = {"error": type(ex).__name__}
                    cache[e["subject"]]["_v"] = CONTENT_VERSION
                    dirty = True
                if "ocr" not in cache[e["subject"]] and ocr.available():
                    try:
                        cache[e["subject"]]["ocr"] = ocr.analyze_photo(path)
                    except Exception as ex:
                        cache[e["subject"]]["ocr"] = {"error": type(ex).__name__, "plates": []}
                    dirty = True
                meta["content"] = cache[e["subject"]]
                if e["data"].get("portal"):
                    meta["portal"] = e["data"]["portal"]
                if cap := e["data"].get("capture"):
                    # captura segura: fecha del servidor y GPS del momento, no los del archivo
                    meta["secure_capture"] = cap
                    meta["taken"] = cap["server_time"]
                    meta["gps"] = [cap["lat"], cap["lon"]] if cap.get("lat") is not None else None
            except Exception as ex:  # formato no soportado, archivo dañado, etc.
                meta = {"error": type(ex).__name__}
            ts = meta.get("taken") or e["ts"].rstrip("Z")
            photos.append(Photo(e["subject"], name, meta, ts, path))
            cam = " ".join(filter(None, [meta.get("make"), meta.get("model")])) or None
            timeline.add_event(ev, ts, name, "foto", None, cam,
                               f"Foto {name}: {json.dumps(meta, ensure_ascii=False, default=str)[:400]}")
    if dirty:
        atomic_json(cache_path, cache)
    if decl is None:
        raise ValueError("el caso no tiene declaración de siniestro")
    return decl, decl_ev, photos


def quick_check(path: Path, name: str, fecha_siniestro: str | None = None) -> tuple[dict, list[Finding]]:
    """Revisa una foto suelta, sin crear un caso (no se registra en la cadena de custodia)."""
    try:
        meta = photo_metadata(path, name)
        if ocr.available() and isinstance(meta.get("content"), dict):
            try:
                meta["content"]["ocr"] = ocr.analyze_photo(path)
            except Exception as ex:
                meta["content"]["ocr"] = {"error": type(ex).__name__, "plates": []}
    except Exception as ex:
        meta = {"error": type(ex).__name__}
    meta["received"] = datetime.now().isoformat(timespec="seconds")
    photo = Photo("0" * 64, name, meta, meta.get("taken") or meta["received"])
    decl = {"numero": "__revision__", "fecha_siniestro": fecha_siniestro or "1900-01-01T00:00:00"}
    findings = analyze(decl, "", [photo], [])
    if not fecha_siniestro:
        findings = [f for f in findings if f.rule not in ("taken_before", "taken_late")]
    for f in findings:
        f.evidence = []
    return meta, findings
