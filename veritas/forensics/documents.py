"""Documentos del siniestro (PDF): presupuestos, facturas, partes, certificados.

Qué revisa:
  1. Que el archivo sea realmente un PDF.
  2. Herramientas de edición en los metadatos (iLovePDF, Smallpdf, Sejda, editores de PDF...).
  3. Modificación posterior a la creación: varias versiones guardadas (actualizaciones
     incrementales) o fecha de modificación muy posterior a la de creación.
  4. Presupuestos o facturas creados antes de la fecha del siniestro.
  5. El mismo documento (idéntico byte a byte) presentado en otro siniestro.

Límites: los metadatos se pueden borrar o falsificar, y un PDF generado de nuevo desde
cero no deja rastro de edición. Un documento sin alertas no está certificado como auténtico.
Lee el texto de los PDF digitales (no de los escaneados, que requieren OCR) y recupera sus versiones anteriores.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from veritas.core.detections import Finding

DOC_EXT = {".pdf"}
IMAGE_DOC_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff"}


class _Done(Exception):
    """Interno: el documento ya quedó leído."""
PDF_EDITORS = ["ilovepdf", "smallpdf", "sejda", "pdfescape", "pdf-xchange editor", "pdfelement",
               "foxit pdf editor", "foxit phantompdf", "nitro pro", "canva", "photoshop", "pdf candy",
               "pdffiller", "dochub", "soda pdf", "sodapdf", "pdf24", "adobe acrobat pro"]
COST_DOC = re.compile(r"presupuest|cotizaci|factura|boleta|reparaci|repuesto|liquidaci", re.I)
EDIT_GAP = timedelta(days=1)

_STR = rb"\(((?:\\.|[^\\)])*)\)"


def _pdf_str(b: bytes) -> str:
    b = re.sub(rb"\\([()\\])", rb"\1", b)
    if b.startswith(b"\xfe\xff"):
        return b[2:].decode("utf-16-be", "ignore")
    return b.decode("latin-1")


def _pdf_date(s: str | None) -> datetime | None:
    m = re.match(r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?", s or "")
    if not m:
        return None
    parts = [int(x) if x else d for x, d in zip(m.groups(), (0, 1, 1, 0, 0, 0))]
    try:
        return datetime(*parts)
    except ValueError:
        return None


def _xmp_date(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s[:19]) if s else None
    except ValueError:
        return None


def pdf_metadata(path: Path) -> dict:
    raw = Path(path).read_bytes()
    meta = {"is_pdf": raw[:1024].lstrip().startswith(b"%PDF"), "revisions": raw.count(b"%%EOF"), "size": len(raw)}
    vals: dict[str, list[str]] = {}
    for key in ("Producer", "Creator", "CreationDate", "ModDate"):
        found = re.findall(rb"/" + key.encode() + rb"\s*" + _STR, raw)
        if found:
            vals[key] = [_pdf_str(x) for x in found]
    xmp = {}
    for tag in ("xmp:CreatorTool", "pdf:Producer", "xmp:CreateDate", "xmp:ModifyDate"):
        m = re.findall(rb"<" + tag.encode() + rb">([^<]*)</", raw)
        if m:
            xmp[tag] = m[-1].decode("utf-8", "ignore")
    tools = vals.get("Producer", []) + vals.get("Creator", []) + [xmp[k] for k in ("pdf:Producer", "xmp:CreatorTool") if k in xmp]
    created = _pdf_date((vals.get("CreationDate") or [""])[0]) or _xmp_date(xmp.get("xmp:CreateDate"))
    modified = _pdf_date((vals.get("ModDate") or [""])[-1]) or _xmp_date(xmp.get("xmp:ModifyDate"))
    meta.update({
        "producer": (vals.get("Producer") or [None])[-1] or xmp.get("pdf:Producer"),
        "creator": (vals.get("Creator") or [None])[0] or xmp.get("xmp:CreatorTool"),
        "tools": sorted(set(t for t in tools if t)),
        "created": created.isoformat() if created else None,
        "modified": modified.isoformat() if modified else None,
    })
    return meta


@dataclass
class Document:
    digest: str
    name: str
    meta: dict
    ts: str

    @property
    def ev(self) -> str:
        return f"{self.digest[:8]}:1"


def load(case, timeline) -> list[Document]:
    import json
    from veritas.forensics import ocr
    docs = []
    cache_path = case.root / "ocr_documentos.json"     # leer un escaneado toma segundos: se guarda por hash
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    dirty = False
    for e in case.active_evidence():
        name = e["data"]["original_name"]
        image_doc = e["data"].get("note") == "documento" and Path(name).suffix.lower() in IMAGE_DOC_EXT
        if Path(name).suffix.lower() not in DOC_EXT and not image_doc:
            continue
        try:
            path = case.evidence_dir / e["subject"]
            if image_doc:
                # documento en papel fotografiado: se lee su texto para revisar RUT, fechas y patentes
                meta = {"is_pdf": False, "image_doc": True, "revisions": 0, "tools": [], "created": None,
                        "modified": None, "text": ""}
                if e["subject"] not in cache and ocr.available():
                    try:
                        from PIL import Image
                        with Image.open(path) as img:
                            cache[e["subject"]] = "\n".join(t for t, sc in ocr.read_image(img) if sc >= 0.5)[:20000]
                    except Exception:
                        cache[e["subject"]] = ""
                    dirty = True
                if cache.get(e["subject"]):
                    meta["text"], meta["ocr"] = cache[e["subject"]], True
                raise _Done
            meta = pdf_metadata(path)
            if meta.get("is_pdf"):
                from veritas.forensics import pdf_versions
                raw = path.read_bytes()
                text, _ = pdf_versions._text(raw)
                meta["text"] = (text or "")[:20000]
                if len(meta["text"].strip()) < 20:                       # sin texto digital: escaneado
                    if e["subject"] not in cache and ocr.available():
                        try:
                            cache[e["subject"]] = ocr.pdf_text(raw)[:20000]
                        except Exception:
                            cache[e["subject"]] = ""
                        dirty = True
                    if cache.get(e["subject"]):
                        meta["text"], meta["ocr"] = cache[e["subject"]], True
                if meta["revisions"] > 1:
                    meta["versions"] = pdf_versions.extract(raw)
        except _Done:
            pass
        except Exception as ex:
            meta = {"error": type(ex).__name__, "is_pdf": False, "revisions": 0, "tools": [], "created": None, "modified": None}
        if (e["data"].get("portal") or {}).get("title"):
            meta["title"] = e["data"]["portal"]["title"]
        ts = meta.get("created") or e["ts"].rstrip("Z")
        d = Document(e["subject"], name, meta, ts)
        docs.append(d)
        tools = ", ".join(meta.get("tools", [])) or "sin datos de software"
        timeline.add_event(d.ev, ts, name, "documento", None, None,
                           f"Documento {name}: {tools}; creado {meta.get('created')}; modificado {meta.get('modified')}; "
                           f"{meta.get('revisions')} versión(es)")
    if dirty:
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return docs


def _fmt(dt: datetime) -> str:
    return dt.strftime("%d-%m-%Y %H:%M")


def analyze(decl: dict, decl_ev: str, docs: list[Document], registry: list[dict]) -> list[Finding]:
    out: list[Finding] = []
    t0 = datetime.fromisoformat(decl["fecha_siniestro"])

    def add(rule, sev, title, summary, cite, d):
        out.append(Finding(rule, sev, title, summary, cite, d.ts, "Documentos"))

    for d in docs:
        m, cite = d.meta, [d.ev]
        if m.get("image_doc"):
            continue                    # foto de un documento: solo aplican las revisiones de su texto
        if not m.get("is_pdf"):
            add("not_pdf", "media", f"Archivo no es un PDF válido ({d.name})",
                f"El archivo {d.name} tiene extensión PDF pero su contenido no corresponde a un PDF.", cite, d)
            continue
        tools = " ".join(m["tools"]).lower()
        if editor := next((e for e in PDF_EDITORS if e in tools), None):
            tool = next(t for t in m["tools"] if editor in t.lower())
            add("doc_editor", "alta", f"Documento pasado por un editor de PDF ({d.name})",
                f"Los metadatos de {d.name} muestran que se procesó con {tool}, una herramienta que permite modificar el contenido.",
                cite, d)
        created = datetime.fromisoformat(m["created"]) if m.get("created") else None
        modified = datetime.fromisoformat(m["modified"]) if m.get("modified") else None
        gap = modified - created if created and modified else None
        if m["revisions"] > 1 or (gap and gap > EDIT_GAP):
            detail = []
            if m["revisions"] > 1:
                detail.append(f"tiene {m['revisions']} versiones guardadas")
            if gap and gap > EDIT_GAP:
                detail.append(f"se modificó el {_fmt(modified)}, {gap.days} día(s) después de crearse")
            add("doc_modified", "media", f"Documento modificado después de creado ({d.name})",
                f"El PDF {d.name} {' y '.join(detail)}.", cite, d)
        if m.get("versions"):
            from veritas.forensics.pdf_versions import findings as version_findings
            out += version_findings(d, cite)
        if COST_DOC.search(d.name) and created and created < t0 - timedelta(hours=1):
            add("doc_before_claim", "alta", f"Presupuesto o factura anterior al siniestro ({d.name})",
                f"El documento {d.name} se creó el {_fmt(created)}, antes del siniestro declarado ({_fmt(t0)}).",
                cite + [decl_ev], d)
        if not created and not m.get("tools"):
            add("doc_no_metadata", "baja", f"Documento sin metadatos ({d.name})",
                f"El PDF {d.name} no indica cuándo ni con qué programa se creó.", cite, d)
        for r in registry:
            if r.get("type") == "doc" and r["sha256"] == d.digest and r["claim"] != decl["numero"]:
                add("reused_doc", "alta", f"Documento ya presentado en otro siniestro ({d.name})",
                    f"El documento {d.name} es idéntico al documento {r['name']} del siniestro {r['claim']}.", cite, d)
                break
    return out
