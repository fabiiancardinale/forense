"""Siniestros de seguros de autos: forense de las fotos que respaldan un reclamo.

Qué revisa en cada foto:
  1. Marcas de generación por IA (C2PA "trainedAlgorithmicMedia", parámetros de
     Stable Diffusion/ComfyUI, nombres de generadores).
  2. Edición con software (Photoshop, Snapseed, PicsArt, etc.).
  3. Ausencia de metadatos (típico de fotos reenviadas por WhatsApp o capturas).
  4. Fecha de la foto contra la fecha declarada del siniestro.
  5. Ubicación GPS de la foto contra el lugar declarado.
  6. Reutilización: la misma foto (o una casi idéntica, recortada o recomprimida)
     ya presentada en otro siniestro, usando hash perceptual y un registro compartido.

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

from PIL import Image

try:                                    # fotos HEIC de iPhone (opcional: pip install pillow-heif)
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

from .detections import Finding
from .chile import norm_plate, plate_format


def chile_plate_ok(p) -> bool:
    return bool(plate_format(p or ""))


def _fmt_plate(p: str) -> str:
    return f"{p[:4]}·{p[4:]}" if plate_format(p) == "nueva" else f"{p[:2]}·{p[2:]}"
from . import image_content, ocr, photo_forensics

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".heic"}
EDITORS = ["photoshop", "lightroom", "gimp", "snapseed", "picsart", "facetune", "pixlr",
           "canva", "affinity", "photopea", "meitu", "remini", "fotor", "polarr"]
AI_MARKERS = [b"trainedAlgorithmicMedia", b"Midjourney", b"DALL-E", b"DALL\xc2\xb7E",
              b"Stable Diffusion", b"stable-diffusion", b"Adobe Firefly", b"ComfyUI", b"NovelAI"]
AI_TEXT_KEYS = ("parameters", "prompt", "workflow")

WHATSAPP_NAME = re.compile(r"(whatsapp[ _]image|IMG-\d{8}-WA\d+)", re.I)
DUP_MAX_DISTANCE = 10       # bits de diferencia en el hash perceptual (de 64); valor usual 8-12
GPS_WARN_KM, GPS_ALERT_KM = 5, 50
BEFORE_TOLERANCE = timedelta(hours=2)
LATE_AFTER = timedelta(days=7)


# ---- metadatos ------------------------------------------------------------
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
            "has_exif": len(exif) > 0, "text_keys": sorted(text), "dhash": dhash(img),
            "forensics": photo_forensics.inspect(img, raw[:4_000_000], name or Path(path).name, dhash),
        }
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

    @property
    def ev(self) -> str:
        return f"{self.digest[:8]}:1"


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
        if ai:
            out.append(Finding("ai_generated", "alta", f"Posible imagen generada por IA ({p.name})",
                               f"La imagen {p.name} contiene marcas de herramientas de generación por IA ({', '.join(ai)}).",
                               cite, p.ts))

        sw = (m.get("software") or "").lower()
        if editor := next((e for e in EDITORS if e in sw), None):
            out.append(Finding("edited", "alta", f"Foto editada ({p.name})",
                               f"Los metadatos de {p.name} indican que pasó por un editor de imágenes ({m['software']}).",
                               cite, p.ts))

        if m.get("secure_capture"):
            from .capture import findings_for
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
            out.append(Finding(rule, sev, f"{title} ({p.name})", f"Foto {p.name}: {text}", cite, p.ts))

        out += content_findings(p, decl, place, cite)

        if place and m.get("gps"):
            km = km_between(place, tuple(m["gps"]))
            if km > GPS_WARN_KM:
                sev = "alta" if km > GPS_ALERT_KM else "media"
                out.append(Finding("gps_mismatch", sev, f"Ubicación no coincide ({p.name})",
                                   f"La foto {p.name} se tomó a {km:.0f} km del lugar declarado ({decl.get('lugar', '')}).",
                                   cite + [decl_ev], p.ts))

        for r in registry:
            if r.get("type", "photo") != "photo" or r["claim"] == decl["numero"]:
                continue
            if r["sha256"] == p.digest:
                how = "idéntica"
            elif hamming(r["dhash"], m["dhash"]) <= DUP_MAX_DISTANCE:
                how = "casi idéntica (recortada, redimensionada o recomprimida)"
            else:
                continue
            out.append(Finding("reused_photo", "alta", f"Foto ya usada en otro siniestro ({p.name})",
                               f"La foto {p.name} es {how} a la foto {r['photo']} del siniestro {r['claim']}.", cite, p.ts))
            break

    for f in out:
        f.category = "Fotos"
    out.sort(key=lambda f: ({"alta": 0, "media": 1, "baja": 2}[f.severity], f.first_ts))
    return out


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
                           f"Veritas leyó en la foto {p.name} la patente {shown}, que no es la del vehículo asegurado "
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
                           f"firma no es válida ({cp.get('state') or 'error'}): la imagen se modificó después de firmada.",
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


def update_registry(path: Path, claim: str, photos: list[Photo], docs=(), decl: dict | None = None,
                    level: str | None = None) -> None:
    """Agrega al registro las fotos, documentos y datos del siniestro (sin duplicar)."""
    reg = load_registry(path)
    known = {(r.get("type", "photo"), r["claim"], r.get("sha256")) for r in reg}
    lines = []
    for p in photos:
        if "dhash" in p.meta and ("photo", claim, p.digest) not in known:
            lines.append({"type": "photo", "claim": claim, "photo": p.name, "sha256": p.digest, "dhash": p.meta["dhash"]})
    for d in docs:
        if ("doc", claim, d.digest) not in known:
            lines.append({"type": "doc", "claim": claim, "name": d.name, "sha256": d.digest})
    if decl is not None:
        from .network import claim_record
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
                if e["subject"] not in cache:
                    try:
                        cache[e["subject"]] = image_content.analyze_image(path)
                    except Exception as ex:
                        cache[e["subject"]] = {"error": type(ex).__name__}
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
            photos.append(Photo(e["subject"], name, meta, ts))
            cam = " ".join(filter(None, [meta.get("make"), meta.get("model")])) or None
            timeline.add_event(ev, ts, name, "foto", None, cam,
                               f"Foto {name}: {json.dumps(meta, ensure_ascii=False, default=str)[:400]}")
    if dirty:
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    if decl is None:
        raise ValueError("el caso no tiene declaración de siniestro")
    return decl, decl_ev, photos


def quick_check(path: Path, name: str, fecha_siniestro: str | None = None) -> tuple[dict, list[Finding]]:
    """Revisa una foto suelta, sin crear un caso (no se registra en la cadena de custodia)."""
    try:
        meta = photo_metadata(path, name)
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
