"""Detecciones basadas en reglas. Cada hallazgo cita los eventos que lo sustentan."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class Finding:
    rule: str
    severity: str  # alta | media | baja
    title: str
    summary: str
    evidence: list[str] = field(default_factory=list)  # IDs de eventos
    first_ts: str = ""
    category: str = ""  # Fotos, Documentos, Póliza y siniestro, Relato, Red de siniestros


def _dt(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")


def brute_force_then_success(events, threshold=5, window_min=10) -> list[Finding]:
    """>= N logons fallidos (4625) seguidos de un logon exitoso (4624) del mismo usuario."""
    out = []
    fails: dict[str, list] = {}
    for e in events:
        if e["event_id"] == 4625 and e["user"]:
            fails.setdefault(e["user"], []).append(e)
        elif e["event_id"] == 4624 and e["user"] and e["user"] in fails:
            recent = [
                f for f in fails[e["user"]]
                if _dt(e["ts"]) - _dt(f["ts"]) <= timedelta(minutes=window_min)
            ]
            if len(recent) >= threshold:
                ids = [f["id"] for f in recent] + [e["id"]]
                out.append(Finding(
                    "brute_force_success", "alta",
                    f"Posible fuerza bruta con acceso exitoso ({e['user']})",
                    f"{len(recent)} intentos fallidos y luego un acceso exitoso del usuario "
                    f"{e['user']} en {window_min} min.",
                    ids, recent[0]["ts"],
                ))
                fails[e["user"]] = []
    return out


def _single(events, event_id, rule, sev, title, tpl, needle=None) -> list[Finding]:
    out = []
    for e in events:
        if e["event_id"] == event_id and (needle is None or needle in (e["message"] or "").lower()):
            out.append(Finding(rule, sev, title, tpl.format(user=e["user"], host=e["host"]),
                               [e["id"]], e["ts"]))
    return out


def run_all(events) -> list[Finding]:
    events = list(events)
    findings: list[Finding] = []
    findings += brute_force_then_success(events)
    findings += _single(events, 1102, "log_cleared", "alta", "Registro de auditoría borrado",
                        "Se borró el registro de seguridad en {host}. Suele indicar ocultamiento de huellas.")
    findings += _single(events, 7045, "service_installed", "media", "Servicio nuevo instalado",
                        "Se instaló un servicio en {host}. Verificar si es legítimo (persistencia).")
    findings += _single(events, 4732, "admin_added", "alta", "Usuario agregado a grupo de administradores",
                        "Se agregó una cuenta a un grupo privilegiado en {host}.", needle="administr")
    findings += _single(events, 4104, "encoded_powershell", "alta", "PowerShell con comando codificado",
                        "Se ejecutó PowerShell ofuscado en {host}.", needle="-enc")
    findings.sort(key=lambda f: f.first_ts)
    return findings
