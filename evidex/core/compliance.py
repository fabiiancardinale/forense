"""Plazos de reporte de incidentes según la Ley 21.663 (Chile).

Alerta inicial: 3 horas desde la detección. Actualización: 72 horas (24 h para OVI).
Informe final: 15 días corridos. Los reglamentos aún pueden cambiar los detalles:
verificar siempre con la ANCI y con asesoría legal antes de usarlo como prueba de cumplimiento.
"""
from __future__ import annotations

from datetime import datetime, timedelta


def deadlines(detected_at: str, ovi: bool = False) -> list[tuple[str, str]]:
    t0 = datetime.strptime(detected_at, "%Y-%m-%dT%H:%M:%SZ")
    fmt = "%Y-%m-%d %H:%M UTC"
    return [
        ("Alerta inicial al CSIRT (3 horas)", (t0 + timedelta(hours=3)).strftime(fmt)),
        (f"Actualización ({'24' if ovi else '72'} horas)",
         (t0 + timedelta(hours=24 if ovi else 72)).strftime(fmt)),
        ("Informe final (15 días corridos)", (t0 + timedelta(days=15)).strftime(fmt)),
    ]
