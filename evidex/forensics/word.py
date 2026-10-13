"""Documentos de Word (.docx) que manda el asegurado, muchas veces con fotos pegadas adentro.

Un .docx es un ZIP con XML. De ahí se sacan:
  - quién lo creó y quién lo guardó por última vez, cuándo, con qué programa (docProps/core.xml y app.xml);
  - el texto (para revisar RUT, patentes y fechas, igual que en los PDF);
  - las imágenes tal como Word las guardó (word/media/), que entran al caso como fotos, cada una marcada
    «extraída de <archivo>.docx». Si Word las comprimió, ya no traen fecha, cámara ni GPS: hay que pedir los originales.

Solo .docx (no el .doc antiguo). Los .docm (con macros) no se aceptan.
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

WORD_EXT = {".docx"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
MAX_IMAGENES = 60
NS = {"cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
      "dc": "http://purl.org/dc/elements/1.1/", "dcterms": "http://purl.org/dc/terms/",
      "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
      "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
GENERICOS = {"", "usuario", "user", "admin", "administrador", "microsoft office user", "usuario de microsoft office",
             "autor", "author", "python-docx", "windows user", "usuario de windows", "pc", "hp", "dell", "lenovo"}


def _xml(z: zipfile.ZipFile, name: str):
    try:
        return ET.fromstring(z.read(name))
    except (KeyError, ET.ParseError):
        return None


def _txt(root, path: str) -> str:
    if root is None:
        return ""
    el = root.find(path, NS)
    return (el.text or "").strip() if el is not None and el.text else ""


def _fecha(s: str) -> str | None:
    """«2026-10-01T12:00:00Z» -> «2026-10-01T12:00:00» (UTC, sin zona, como las fechas de los PDF)."""
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo:
            d = d.astimezone(timezone.utc).replace(tzinfo=None)
        return d.isoformat(timespec="seconds")
    except ValueError:
        return None


def _tiene_datos(data: bytes) -> bool:
    """¿La imagen trae fecha o cámara (EXIF)?"""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            ex = im.getexif()
            return bool(ex.get(306) or ex.get(271) or ex.get(272) or ex.get_ifd(0x8769).get(36867))
    except Exception:
        return False


def _imagenes(z: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    out = [i for i in z.infolist() if i.filename.startswith("word/media/")
           and Path(i.filename).suffix.lower() in IMG_EXT and i.file_size > 0]
    return sorted(out, key=lambda i: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", i.filename)])[:MAX_IMAGENES]


def metadata(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        core, app = _xml(z, "docProps/core.xml"), _xml(z, "docProps/app.xml")
        doc = _xml(z, "word/document.xml")
        texto = ""
        if doc is not None:
            parrafos = []
            for p in doc.iter(f"{{{NS['w']}}}p"):
                parrafos.append("".join(t.text or "" for t in p.iter(f"{{{NS['w']}}}t")))
            texto = "\n".join(x for x in parrafos if x.strip())
        imgs = _imagenes(z)
        con_datos = sum(1 for i in imgs if _tiene_datos(z.read(i)))
        try:
            places = _placements(z)
            con_nombre = sum(1 for i in imgs if _original_name(places.get(i.filename, [])))
        except Exception:
            con_nombre = 0
    app_name = _txt(app, "ep:Application")
    version = _txt(app, "ep:AppVersion")
    return {"word": True, "creator": _txt(core, "dc:creator"), "last_modified_by": _txt(core, "cp:lastModifiedBy"),
            "created": _fecha(_txt(core, "dcterms:created")), "modified": _fecha(_txt(core, "dcterms:modified")),
            "revision": _txt(core, "cp:revision"), "company": _txt(app, "ep:Company"),
            "tools": [x for x in [" ".join(filter(None, [app_name, version]))] if x],
            "producer": " ".join(filter(None, [app_name, version])) or None,
            "text": texto[:20000], "images": len(imgs), "images_with_data": con_datos,
            "images_named": con_nombre}


def extract_images(path: Path, dest: Path, base: str) -> list[Path]:
    """Copia las imágenes del Word, sin cambiarlas, a `dest`, con nombres «<base>_imagen<N>.<ext>»."""
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    with zipfile.ZipFile(path) as z:
        for n, info in enumerate(_imagenes(z), 1):
            ext = Path(info.filename).suffix.lower()
            p = dest / f"{base}_imagen{n}{'.jpg' if ext == '.jpeg' else ext}"
            p.write_bytes(z.read(info))
            out.append(p)
    return out


def generico(nombre: str) -> bool:
    return nombre.strip().lower() in GENERICOS


def mismo_nombre(a: str, b: str) -> bool:
    """¿Comparten un apellido o nombre (de 3 letras o más)? «J. Pérez» y «Juan Pérez Soto» sí."""
    def palabras(s):
        import unicodedata
        s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
        return {w for w in re.findall(r"[a-z]{3,}", s)}
    return bool(palabras(a) & palabras(b))


# ---- lo que queda de cada imagen dentro del Word ------------------------------------------------------
# Word casi siempre borra la fecha, la cámara y el GPS de las fotos (o ya venían sin ellos por WhatsApp).
# Pero el documento guarda otras pistas: el nombre original del archivo que se pegó (que muchas veces trae la
# fecha y la hora: IMG_20260912_153210.jpg, «WhatsApp Image 2026-09-12 at 15.32.10.jpeg»), el texto que el
# asegurado escribió junto a la imagen, el tamaño original, si Word la comprimió y lo que sobrevive en la
# imagen (XMP, perfil de color, calidad de compresión).
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
NS_PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
NS_V = "urn:schemas-microsoft-com:vml"
NS_O = "urn:schemas-microsoft-com:office:office"
GENERIC_IMG = re.compile(r"^(imagen|image|picture|imagem|gr[aá]fico|figura|foto|photo|img|dibujo|drawing|"
                         r"cuadro de texto|text box)?\s*\d*(\.\w{3,4})?$", re.I)
EMU_PER_CM = 360000
# nombres que ponen los teléfonos y las apps (fecha y, a veces, hora)
NAME_DATES = [
    (re.compile(r"(?:Captura de pantalla|Screenshot|Screen Shot)[ _]?(20\d{2})-?(\d{2})-?(\d{2})(?:[ _-]a? ?(?:las )?(\d{2})[.:]?(\d{2})[.:]?(\d{2}))?", re.I), "captura de pantalla"),
    (re.compile(r"(?:IMG|PXL|VID|PANO|MVIMG|Screenshot|Captura|DSC|Photo)?[_-]?(20\d{2})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})", re.I), "teléfono"),
    (re.compile(r"WhatsApp Image (20\d{2})-(\d{2})-(\d{2}) at (\d{1,2})\.(\d{2})\.(\d{2})", re.I), "WhatsApp"),
    (re.compile(r"(?:IMG|VID)-(20\d{2})(\d{2})(\d{2})-WA\d+", re.I), "WhatsApp"),
    (re.compile(r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})[ _T](\d{2})[.:-](\d{2})[.:-](\d{2})"), "nombre del archivo"),
]


def date_from_name(name: str) -> tuple[str, str] | None:
    """Fecha (ISO, sin zona) que el teléfono o la app escribió en el nombre del archivo, y de dónde viene."""
    for rx, origin in NAME_DATES:
        m = rx.search(name or "")
        if not m:
            continue
        g = [int(x) if x else 0 for x in m.groups()] + [0, 0, 0]
        try:
            d = datetime(g[0], g[1], g[2], g[3], g[4], g[5])
        except ValueError:
            continue
        if 2005 <= d.year <= datetime.now().year + 1:
            has_time = len([x for x in m.groups() if x]) > 3
            return d.isoformat(timespec="seconds" if has_time else "seconds")[:19 if has_time else 10], origin
    return None


def _rels(z: zipfile.ZipFile, part: str) -> dict[str, str]:
    folder, name = part.rsplit("/", 1)
    root = _xml(z, f"{folder}/_rels/{name}.rels")
    out = {}
    if root is not None:
        for r in root.iter(f"{{{NS_PKG_REL}}}Relationship"):
            t = r.get("Target") or ""
            out[r.get("Id")] = t.lstrip("/") if t.startswith("/") else f"{folder}/{t}"
    return out


def _norm(path: str) -> str:
    parts = []
    for p in path.split("/"):
        if p == "..":
            parts and parts.pop()
        elif p and p != ".":
            parts.append(p)
    return "/".join(parts)


def _placements(z: zipfile.ZipFile) -> dict[str, list[dict]]:
    """Dónde aparece cada imagen en el texto: nombre y descripción que guardó Word, tamaño en la página y el
    texto del párrafo (o los vecinos) donde está."""
    out: dict[str, list[dict]] = {}
    parts = ["word/document.xml"] + sorted(n for n in z.namelist() if re.match(r"word/(header|footer)\d*\.xml$", n))
    for part in parts:
        root = _xml(z, part)
        if root is None:
            continue
        rels = _rels(z, part)
        paras = list(root.iter(f"{{{NS['w']}}}p"))
        texts = ["".join(t.text or "" for t in p.iter(f"{{{NS['w']}}}t")).strip() for p in paras]
        for i, p in enumerate(paras):
            near = texts[i] or next((texts[j] for j in (i + 1, i - 1) if 0 <= j < len(texts) and texts[j]
                                     and len(texts[j]) < 200), "")
            for d in p.iter(f"{{{NS['w']}}}drawing"):
                doc_pr = next(d.iter(f"{{{NS_WP}}}docPr"), None)
                c_nv = next(d.iter(f"{{{NS_PIC}}}cNvPr"), None)
                ext = next(d.iter(f"{{{NS_WP}}}extent"), None)
                for blip in d.iter(f"{{{NS_A}}}blip"):
                    target = rels.get(blip.get(f"{{{NS_REL}}}embed") or blip.get(f"{{{NS_REL}}}link") or "")
                    if not target:
                        continue
                    names = [x for x in ((doc_pr.get("name") if doc_pr is not None else None),
                                         (c_nv.get("name") if c_nv is not None else None)) if x]
                    descr = " ".join(x for x in ((doc_pr.get("descr") if doc_pr is not None else None),
                                                 (doc_pr.get("title") if doc_pr is not None else None),
                                                 (c_nv.get("descr") if c_nv is not None else None)) if x)
                    cm = None
                    if ext is not None:
                        try:
                            cm = (round(int(ext.get("cx")) / EMU_PER_CM, 1), round(int(ext.get("cy")) / EMU_PER_CM, 1))
                        except (TypeError, ValueError):
                            pass
                    out.setdefault(_norm(target), []).append({"names": names, "descr": descr.strip(), "cm": cm,
                                                              "text": near[:200], "part": part})
            for im in p.iter(f"{{{NS_V}}}imagedata"):                     # imágenes de documentos antiguos (VML)
                target = rels.get(im.get(f"{{{NS_REL}}}id") or "")
                if target:
                    out.setdefault(_norm(target), []).append({"names": [], "descr": im.get(f"{{{NS_O}}}title") or "",
                                                              "cm": None, "text": near[:200], "part": part})
    return out


def _original_name(places: list[dict]) -> str | None:
    """El nombre del archivo que se pegó, si Word lo conservó (no «Imagen 3»)."""
    for pl in places:
        for cand in pl["names"] + [pl["descr"]]:
            cand = (cand or "").strip()
            cand = re.split(r"[\\/]", cand)[-1] if re.search(r"[\\/]", cand) else cand
            if cand and not GENERIC_IMG.match(cand) and (re.search(r"\.(jpe?g|png|heic|webp|gif|bmp|tiff?)$", cand, re.I)
                                                         or date_from_name(cand)):
                return cand[:120]
    return None


def _clues(info: dict, deep: dict) -> list[str]:
    """Pistas de por dónde pasó la imagen antes de llegar al Word. Son indicios, no pruebas."""
    out = []
    w, h = info.get("px") or (0, 0)
    big, small = max(w, h), min(w, h)
    q = (deep.get("jpeg") or {}).get("Calidad estimada")
    dpi = info.get("dpi")
    orig = info.get("original_name") or ""
    if re.search(r"whatsapp|-WA\d", orig, re.I):
        out.append("El nombre original es de WhatsApp: la foto se recibió o se guardó desde WhatsApp, que borra la fecha, "
                   "la cámara y el GPS.")
    elif big in (1600, 1280, 2560, 1599, 2048) and info.get("format") == "JPEG" and not info.get("exif"):
        out.append(f"Mide {w}×{h}, el tamaño al que WhatsApp achica las fotos: probablemente pasó por WhatsApp antes "
                   "de pegarse en el Word.")
    if info.get("format") == "PNG" and big >= 1000 and (round(big / max(small, 1), 2) >= 1.9):
        out.append(f"Es un PNG de {w}×{h}, proporción de pantalla de celular: parece una captura de pantalla, no la foto original.")
    if dpi and round(dpi) in (96, 150, 220, 330) and not info.get("exif"):
        out.append(f"Tiene {round(dpi)} ppp, la resolución a la que Word comprime las imágenes: Word la achicó y le "
                   "borró los datos al guardar.")
    if big >= 3000 and not info.get("exif"):
        out.append(f"Conserva un tamaño de cámara ({w}×{h}) pero no sus datos: se borraron sin achicarla "
                   "(por ejemplo, con una app o al editarla).")
    if q and q < 75:
        out.append(f"Calidad de compresión baja ({q} de 100): se volvió a guardar al menos una vez.")
    icc = deep.get("icc") or {}
    if "P3" in (icc.get("Nombre") or ""):
        out.append(f"Perfil de color «{icc['Nombre']}», el que usan iPhone y algunos Samsung: el original era de un celular.")
    return out


def image_details(path: Path) -> dict[str, dict]:
    """Por cada imagen del Word (clave: nombre interno, p. ej. «word/media/image1.jpeg»): nombre original, fecha
    según ese nombre, texto junto a la imagen, tamaño, qué metadatos sobreviven y pistas de su origen."""
    from evidex.forensics import deep_meta
    import tempfile
    out = {}
    with zipfile.ZipFile(path) as z:
        places = _placements(z)
        for info in _imagenes(z):
            data = z.read(info)
            pl = places.get(info.filename, [])
            import hashlib
            d: dict = {"media": info.filename, "sha256": hashlib.sha256(data).hexdigest(), "times_used": len(pl), "texts": [p["text"] for p in pl if p["text"]][:3],
                       "cm": next((p["cm"] for p in pl if p["cm"]), None), "bytes": len(data)}
            d["original_name"] = _original_name(pl)
            path_txt = next((x for p in pl for x in p["names"] + [p["descr"]] if re.search(r"[A-Za-z]:\\|/Users/|/home/|\\Users\\", x or "")), None)
            if path_txt:
                d["original_path"] = path_txt[:200]          # Word antiguo guarda la ruta completa del archivo pegado
            alt = next((p["descr"] for p in pl if p["descr"] and p["descr"] != d["original_name"]), "")
            if alt:
                d["alt"] = alt[:200]
            nd = date_from_name(d["original_name"] or "")
            if nd:
                d["name_date"], d["name_date_origin"] = nd
            try:
                from PIL import Image
                with Image.open(io.BytesIO(data)) as im:
                    d["format"], d["px"] = im.format, list(im.size)
                    dpi = (im.info.get("dpi") or (None,))[0]
                    d["dpi"] = float(dpi) if dpi else None
                    d["exif"] = bool(im.getexif())
            except Exception:
                d["format"] = Path(info.filename).suffix.lstrip(".").upper()
            deep = {}
            try:
                with tempfile.NamedTemporaryFile(suffix=Path(info.filename).suffix) as tf:
                    tf.write(data)
                    tf.flush()
                    deep = deep_meta.read_all(tf.name, raw=data)
            except Exception:
                pass
            dates = deep.get("dates") or {}
            if dates:
                d["inner_dates"] = {k: str(v)[:19] for k, v in list(dates.items())[:6]}
            xmp = deep.get("xmp") or {}
            if xmp:
                d["xmp"] = {k: str(v)[:120] for k, v in list(xmp.items())[:12]}
            icc = deep.get("icc") or {}
            if icc.get("Nombre"):
                d["icc"] = icc["Nombre"]
            q = (deep.get("jpeg") or {}).get("Calidad estimada")
            if q:
                d["quality"] = q
            d["ai"] = list(deep.get("ai") or [])[:3]
            d["edits"] = list(deep.get("edits") or [])[:3]
            d["clues"] = _clues(d, deep)
            out[info.filename] = d
    return out


@__import__("functools").lru_cache(maxsize=32)
def _details_cached(path: str, mtime: float, size: int) -> dict[str, dict]:
    return {d["sha256"]: d for d in image_details(Path(path)).values()}


def details_for_image(doc_path: Path, image_sha256: str) -> dict:
    """Lo que el Word guarda de una imagen ya sacada (para casos subidos antes de que Evidex lo leyera)."""
    try:
        st = Path(doc_path).stat()
        return _details_cached(str(doc_path), st.st_mtime, st.st_size).get(image_sha256) or {}
    except Exception:
        return {}
