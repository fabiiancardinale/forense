"""Reglas sobre los datos de la póliza y del siniestro (indicadores clásicos de fraude).

Son señales de priorización ampliamente usadas en la industria, no pruebas. Los umbrales
son valores iniciales razonables y deben calibrarse con los datos reales de la aseguradora.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from evidex.core.detections import Finding

EARLY_ALERT_DAYS, EARLY_WARN_DAYS = 10, 30      # siniestro cerca del inicio de la póliza
NEAR_END_DAYS = 15                              # siniestro cerca del vencimiento
COVERAGE_CHANGE_DAYS = 30                       # aumento de cobertura poco antes
LATE_WARN_DAYS, LATE_ALERT_DAYS = 7, 30         # aviso tardío
NEAR_LIMIT_RATIO = 0.9                          # monto reclamado vs suma asegurada


def parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip()[:19]).date()
    except ValueError:
        return None


def parse_amount(value) -> int | None:
    """Acepta 4650000, "4.650.000", "$4.650.000", "4650000.0"."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip().replace("$", "").replace(" ", "")
    if m := re.fullmatch(r"(\d+)[.,]\d{1,2}", s):  # 4650000.0 o 4650000,50: se ignoran los decimales
        s = m.group(1)
    digits = re.sub(r"\D", "", s)  # 4.650.000 -> 4650000
    return int(digits) if digits else None


def parse_int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _money(n: int) -> str:
    return "$" + f"{n:,}".replace(",", ".")


def _f(rule, sev, title, summary, decl_ev, ts):
    return Finding(rule, sev, title, summary, [decl_ev], ts, "Póliza y siniestro")


def analyze(decl: dict, decl_ev: str) -> list[Finding]:
    out: list[Finding] = []
    t0 = datetime.fromisoformat(decl["fecha_siniestro"])
    ts = decl["fecha_siniestro"]
    d0 = t0.date()

    if inicio := parse_date(decl.get("inicio_poliza")):
        days = (d0 - inicio).days
        if days < 0:
            out.append(_f("before_policy", "alta", "Siniestro anterior al inicio de la póliza",
                          f"El siniestro ({d0:%d-%m-%Y}) es anterior al inicio de vigencia de la póliza ({inicio:%d-%m-%Y}).",
                          decl_ev, ts))
        elif days <= EARLY_WARN_DAYS:
            out.append(_f("early_claim", "alta" if days <= EARLY_ALERT_DAYS else "media",
                          "Siniestro poco después de contratar la póliza",
                          f"El siniestro ocurrió {days} día(s) después del inicio de la póliza ({inicio:%d-%m-%Y}).",
                          decl_ev, ts))

    if fin := parse_date(decl.get("fin_poliza")):
        days = (fin - d0).days
        if days < 0:
            out.append(_f("after_policy", "alta", "Siniestro posterior al vencimiento de la póliza",
                          f"La póliza venció el {fin:%d-%m-%Y}, antes del siniestro.", decl_ev, ts))
        elif days <= NEAR_END_DAYS:
            out.append(_f("near_end", "media", "Siniestro cerca del vencimiento de la póliza",
                          f"El siniestro ocurrió {days} día(s) antes del vencimiento de la póliza ({fin:%d-%m-%Y}).",
                          decl_ev, ts))

    if cambio := parse_date(decl.get("cambio_cobertura")):
        days = (d0 - cambio).days
        if 0 <= days <= COVERAGE_CHANGE_DAYS:
            out.append(_f("coverage_change", "alta", "Aumento de cobertura poco antes del siniestro",
                          f"La cobertura se modificó el {cambio:%d-%m-%Y}, {days} día(s) antes del siniestro.",
                          decl_ev, ts))

    if denuncia := parse_date(decl.get("fecha_denuncia")):
        days = (denuncia - d0).days
        if days < 0:
            out.append(_f("report_before", "alta", "Denuncia anterior al siniestro",
                          f"La denuncia ({denuncia:%d-%m-%Y}) tiene fecha anterior al siniestro declarado.", decl_ev, ts))
        elif days > LATE_WARN_DAYS:
            out.append(_f("late_report", "alta" if days > LATE_ALERT_DAYS else "media", "Aviso tardío del siniestro",
                          f"El siniestro se denunció {days} días después de ocurrido.", decl_ev, ts))

    monto, suma = parse_amount(decl.get("monto_reclamado")), parse_amount(decl.get("suma_asegurada"))
    if monto and suma and monto >= NEAR_LIMIT_RATIO * suma:
        out.append(_f("near_limit", "media", "Monto reclamado cercano al tope",
                      f"Se reclaman {_money(monto)}, el {100 * monto / suma:.0f}% de la suma asegurada ({_money(suma)}).",
                      decl_ev, ts))

    testigos = parse_int(decl.get("testigos"))
    if t0.hour < 6 and not testigos and not decl.get("parte_policial"):
        out.append(_f("night_no_witness", "media", "Siniestro de madrugada sin testigos ni parte policial",
                      f"El siniestro se declaró a las {t0:%H:%M}, sin testigos ni número de parte policial.", decl_ev, ts))
    return out
