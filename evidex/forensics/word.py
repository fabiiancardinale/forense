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
    app_name = _txt(app, "ep:Application")
    version = _txt(app, "ep:AppVersion")
    return {"word": True, "creator": _txt(core, "dc:creator"), "last_modified_by": _txt(core, "cp:lastModifiedBy"),
            "created": _fecha(_txt(core, "dcterms:created")), "modified": _fecha(_txt(core, "dcterms:modified")),
            "revision": _txt(core, "cp:revision"), "company": _txt(app, "ep:Company"),
            "tools": [x for x in [" ".join(filter(None, [app_name, version]))] if x],
            "producer": " ".join(filter(None, [app_name, version])) or None,
            "text": texto[:20000], "images": len(imgs), "images_with_data": con_datos}


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
