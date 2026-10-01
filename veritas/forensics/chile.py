"""Validación de datos chilenos: RUT (dígito verificador) y patentes.

Un RUT con dígito verificador incorrecto en una factura o presupuesto no puede venir del
sistema de un taller o del SII (ambos lo calculan): indica un documento escrito a mano o
fabricado. Una patente con formato imposible, o distinta en la declaración y en los
documentos, indica un error de digitación o un documento de otro vehículo.
"""
from __future__ import annotations

import re

RUT_RE = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d{3}){2}|\d{7,8})\s*-\s*([\dkK])(?![\w])")
# patentes: nuevas desde 2007 (BBBB·12, sin vocales ni M, N, Ñ, Q) y antiguas (AB·1234); motos BBB·12 / AB·123
NEW_LETTERS = "BCDFGHJKLPRSTVWXYZ"
PLATE_NEW = re.compile(rf"\b([{NEW_LETTERS}]{{4}})[\s·.\-]?(\d{{2}})\b")
PLATE_OLD = re.compile(r"\b([A-Z]{2})[\s·.\-]?(\d{4})\b")
PLATE_ANY = re.compile(r"\b([A-Z]{2,4})[\s·.\-]?(\d{2,4})\b")


def rut_dv(body: int) -> str:
    """Dígito verificador por módulo 11."""
    s, m = 0, 2
    while body:
        s += (body % 10) * m
        body //= 10
        m = 2 if m == 7 else m + 1
    r = 11 - s % 11
    return "0" if r == 11 else "K" if r == 10 else str(r)


def rut_parts(text: str) -> tuple[int, str] | None:
    m = RUT_RE.search(str(text or ""))
    if not m:
        return None
    return int(m.group(1).replace(".", "")), m.group(2).upper()


def rut_valid(text: str) -> bool | None:
    """True/False si es un RUT reconocible; None si no tiene forma de RUT."""
    p = rut_parts(text)
    if not p:
        return None
    return rut_dv(p[0]) == p[1]


def fmt_rut(body: int, dv: str) -> str:
    return f"{body:,}".replace(",", ".") + "-" + dv


def ruts_in(text: str) -> list[tuple[str, bool]]:
    """RUT encontrados en un texto, con su validez. Ignora duplicados."""
    seen, out = set(), []
    for m in RUT_RE.finditer(text or ""):
        body, dv = int(m.group(1).replace(".", "")), m.group(2).upper()
        if body < 1_000_000 or (body, dv) in seen:   # números cortos suelen ser montos o folios
            continue
        seen.add((body, dv))
        out.append((fmt_rut(body, dv), rut_dv(body) == dv))
    return out


def norm_plate(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def plate_format(text: str) -> str | None:
    """'nueva', 'antigua', 'moto' o None si no es una patente chilena válida."""
    p = norm_plate(text)
    if re.fullmatch(rf"[{NEW_LETTERS}]{{4}}\d{{2}}", p):
        return "nueva"
    if re.fullmatch(r"[A-Z]{2}\d{4}", p) and not p.endswith("0000"):
        return "antigua"
    if re.fullmatch(rf"[{NEW_LETTERS}]{{3}}\d{{2}}|[A-Z]{{2}}\d{{3}}", p):
        return "moto"
    return None


def plates_in(text: str) -> list[str]:
    """Patentes con formato válido mencionadas en un texto (normalizadas, sin repetir)."""
    out = []
    up = (text or "").upper()
    for rx in (PLATE_NEW, PLATE_OLD):
        for m in rx.finditer(up):
            p = m.group(1) + m.group(2)
            if p not in out and plate_format(p):
                out.append(p)
    return out


# ---- hallazgos -------------------------------------------------------------------------------
def analyze(decl: dict, decl_ev: str, docs) -> list:
    from veritas.core.detections import Finding
    out = []
    ts = decl.get("fecha_siniestro", "")

    def add(rule, sev, title, summary, cite):
        out.append(Finding(rule, sev, title, summary, cite, ts, "Datos del asegurado"))

    if decl.get("rut") and rut_valid(decl["rut"]) is False:
        body, dv = rut_parts(decl["rut"])
        add("rut_invalid", "media", "RUT del asegurado con dígito verificador incorrecto",
            f"El RUT declarado ({decl['rut']}) no es válido: para {fmt_rut(body, '')[:-1]} el dígito verificador "
            f"debería ser {rut_dv(body)}. Puede ser un error de digitación o un RUT inventado.", [decl_ev])
    plate = decl.get("patente")
    if plate and not plate_format(plate):
        add("plate_invalid", "media", "Patente con formato inválido",
            f"La patente declarada ({plate}) no tiene un formato de patente chilena (BBBB·12 o AB·1234).", [decl_ev])

    declared = norm_plate(plate) if plate else ""
    for d in docs:
        text = d.meta.get("text") or ""
        if not text:
            continue
        bad = [r for r, ok in ruts_in(text) if not ok]
        if bad:
            add("doc_rut_invalid", "alta", f"RUT inválido en un documento ({d.name})",
                f"El documento {d.name} contiene {'el RUT' if len(bad) == 1 else 'los RUT'} {', '.join(bad)} con dígito verificador "
                "incorrecto. Los sistemas de facturación y el SII lo calculan solos: un RUT inválido indica un "
                "documento escrito a mano o fabricado.", [d.ev])
        others = [p for p in plates_in(text) if p != declared]
        if declared and plate_format(declared) and others and declared not in plates_in(text):
            add("doc_plate_mismatch", "media", f"El documento menciona otra patente ({d.name})",
                f"El documento {d.name} menciona la patente {', '.join(others)} y no la del vehículo declarado ({plate}). "
                "Puede ser un documento de otro vehículo.", [d.ev, decl_ev])
    return out
