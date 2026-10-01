"""Versiones ocultas de un PDF.

Cuando alguien edita un PDF y lo guarda (Acrobat, iLovePDF, editores en línea), muchos
programas no reescriben el archivo: agregan los cambios al final ("actualización
incremental"). La versión original sigue dentro del archivo, completa. Cortando el archivo
en cada marca de fin (%%EOF) se recupera cada versión tal como era, y comparando su texto
se ve exactamente qué cambió: montos, fechas, patentes, nombres.

Límites: si el documento se exportó de nuevo desde cero ("Guardar como" con optimización,
imprimir a PDF), no quedan versiones anteriores. Un PDF linealizado puede tener dos marcas
de fin sin haber sido editado; por eso solo se informan versiones que se pueden abrir y
cuyo texto cambió.
"""
from __future__ import annotations

import difflib
import io
import re
from datetime import datetime

AMOUNT = re.compile(r"\$\s?\d{1,3}(?:\.\d{3})+(?:,\d+)?|\b\d{1,3}(?:\.\d{3}){1,3}\b")
DATE = re.compile(r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b")
_STR = rb"\(((?:\\.|[^\\)])*)\)"


def eof_offsets(raw: bytes) -> list[int]:
    """Fin de cada versión (posición después de %%EOF y su salto de línea)."""
    ends = []
    for m in re.finditer(rb"%%EOF", raw):
        end = m.end()
        while end < len(raw) and raw[end:end + 1] in b"\r\n":
            end += 1
        ends.append(end)
    return ends


def _text(data: bytes, max_pages: int = 20) -> tuple[str | None, int]:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = pdf.pages[:max_pages]
            return "\n".join((p.extract_text() or "") for p in pages), len(pdf.pages)
    except Exception:
        return None, 0


def _segment_meta(seg: bytes) -> dict:
    out = {}
    for key in ("Producer", "ModDate", "CreationDate"):
        found = re.findall(rb"/" + key.encode() + rb"\s*" + _STR, seg)
        if found:
            out[key] = found[-1].decode("latin-1", "ignore")
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?", out.get("ModDate", ""))
    if m:
        try:
            out["modified"] = datetime(*[int(x or 0) for x in m.groups()]).isoformat()
        except ValueError:
            pass
    return out


def extract(raw: bytes) -> dict:
    """{'versions': [...], 'changes': [...]} con el texto y los cambios entre versiones legibles."""
    ends = eof_offsets(raw)
    versions, prev_end = [], 0
    for i, end in enumerate(ends, 1):
        text, pages = _text(raw[:end])
        meta = _segment_meta(raw[prev_end:end])
        versions.append({"n": i, "end": end, "size": end, "pages": pages, "readable": text is not None and pages > 0,
                         "producer": meta.get("Producer"), "modified": meta.get("modified"), "text": text or ""})
        prev_end = end
    readable = [v for v in versions if v["readable"]]
    changes = []
    for a, b in zip(readable, readable[1:]):
        if a["text"].strip() == b["text"].strip():
            continue
        old_lines = [l.strip() for l in a["text"].splitlines() if l.strip()]
        new_lines = [l.strip() for l in b["text"].splitlines() if l.strip()]
        removed, added = [], []
        for d in difflib.ndiff(old_lines, new_lines):
            if d.startswith("- "):
                removed.append(d[2:])
            elif d.startswith("+ "):
                added.append(d[2:])
        old_t, new_t = "\n".join(removed), "\n".join(added)
        am_old = [x for x in AMOUNT.findall(old_t) if x not in AMOUNT.findall(new_t)]
        am_new = [x for x in AMOUNT.findall(new_t) if x not in AMOUNT.findall(old_t)]
        dt_old = [x for x in DATE.findall(old_t) if x not in DATE.findall(new_t)]
        dt_new = [x for x in DATE.findall(new_t) if x not in DATE.findall(old_t)]
        changes.append({"from": a["n"], "to": b["n"], "removed": removed[:30], "added": added[:30],
                        "amounts": [am_old, am_new], "dates": [dt_old, dt_new],
                        "modified": b.get("modified"), "producer": b.get("producer")})
    for v in versions:
        v["text"] = v["text"][:4000]
    return {"versions": versions, "changes": changes}


def version_bytes(raw: bytes, n: int) -> bytes | None:
    ends = eof_offsets(raw)
    return raw[:ends[n - 1]] if 1 <= n <= len(ends) else None


def findings(doc, cite) -> list:
    """Hallazgos para un documento con versiones recuperadas."""
    from veritas.core.detections import Finding
    pv = doc.meta.get("versions") or {}
    out = []
    for ch in pv.get("changes", []):
        (am_o, am_n), (dt_o, dt_n) = ch["amounts"], ch["dates"]
        when = f" el {datetime.fromisoformat(ch['modified']):%d-%m-%Y %H:%M}" if ch.get("modified") else ""
        tool = f" con {ch['producer']}" if ch.get("producer") else ""
        parts = []
        if am_o or am_n:
            parts.append(f"el monto pasó de {', '.join(am_o) or '—'} a {', '.join(am_n) or '—'}")
        if dt_o or dt_n:
            parts.append(f"la fecha pasó de {', '.join(dt_o) or '—'} a {', '.join(dt_n) or '—'}")
        if parts:
            out.append(Finding("doc_version_changed", "alta", f"Versión anterior del documento con otros datos ({doc.name})",
                               f"Dentro de {doc.name} se recuperó la versión {ch['from']} original. En la versión {ch['to']}, "
                               f"guardada{when}{tool}, {' y '.join(parts)}. La versión anterior se puede descargar "
                               "desde el caso para compararla.", cite, doc.ts, "Documentos"))
        else:
            sample = (ch["added"] or ch["removed"] or [""])[0][:120]
            out.append(Finding("doc_version_text", "media", f"El texto del documento cambió entre versiones ({doc.name})",
                               f"El documento {doc.name} tiene una versión anterior recuperable con texto distinto "
                               f"({len(ch['removed'])} línea(s) quitadas, {len(ch['added'])} agregadas; por ejemplo: “{sample}”).",
                               cite, doc.ts, "Documentos"))
    return out
