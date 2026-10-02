"""Quién trabaja cada siniestro: analista responsable y derivación a un perito o empresa externa.

Todo queda en la cadena de custodia del caso (no en un archivo aparte que se pueda editar):
  case_assigned          el caso pasa a un analista (al registrarlo, o reasignado por el jefe)
  case_derived           el analista deriva las entrevistas a una empresa de peritaje, con plazo
  derivation_delivered   el perito entregó su informe final
  derivation_cancelled   se anuló la derivación (por ejemplo, para cambiar de empresa)

La derivación crea un expediente de investigación (evidex.investigations.dossier) enlazado al
siniestro; el perito trabaja ese expediente y el analista ve su avance desde el caso.
"""
from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from evidex.core.case import Case

STALE_DAYS = 7          # un caso abierto sin movimiento por más días que esto se considera atrasado
DERIVATION_STATES = {"derivado": "Derivado, sin iniciar", "en_curso": "En curso", "entregado": "Informe entregado",
                     "atrasado": "Atrasado", "anulado": "Anulado"}


# ---- analista responsable ------------------------------------------------------------------
def owner(case: Case) -> dict | None:
    """Última asignación: {"user", "name", "by", "ts", "reason"} o None si nunca se asignó."""
    last = next((e for e in reversed(case.ledger.entries()) if e["action"] == "case_assigned"), None)
    if not last:
        return None
    return {"user": last["subject"], "name": last["data"].get("name") or last["subject"], "by": last["actor"],
            "ts": last["ts"], "reason": last["data"].get("reason", "")}


def assign(case: Case, username: str, name: str, actor: str, reason: str = "") -> dict:
    return case.ledger.append(actor, "case_assigned", username, {"name": name, "reason": reason})


def assignment_history(case: Case) -> list[dict]:
    return [e for e in case.ledger.entries() if e["action"] == "case_assigned"]


# ---- derivación a peritos --------------------------------------------------------------------
def derivation(case: Case) -> dict | None:
    """Derivación vigente con su estado, o None. Una derivación anulada deja de ser vigente."""
    current = None
    for e in case.ledger.entries():
        if e["action"] == "case_derived":
            current = {**e["data"], "ts": e["ts"], "by": e["actor"], "delivered": None}
        elif e["action"] == "derivation_cancelled" and current:
            current = None
        elif e["action"] == "derivation_delivered" and current:
            current["delivered"] = e["ts"]
    if current:
        current["started"] = _started(case.root.parent / current.get("dossier", ""))
        current["state"] = _state(current)
        current["state_label"] = DERIVATION_STATES[current["state"]]
    return current


def _started(dossier_dir: Path) -> bool:
    """El perito ya trabajó el expediente: hay algo más que su creación."""
    try:
        lines = (dossier_dir / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return any(json.loads(x)["action"] in ("evidence_added", "alert_response", "conclusion") and
               json.loads(x)["data"].get("note") != "expediente" for x in lines[2:] if x.strip())


def _state(d: dict) -> str:
    if d.get("delivered"):
        return "entregado"
    if d.get("plazo") and date.fromisoformat(d["plazo"]) < date.today():
        return "atrasado"
    return "en_curso" if d.get("started") else "derivado"


def derive(workdir: Path, case: Case, decl: dict, empresa: str, perito: str, plazo: str, instrucciones: str,
           actor: str, alertas: list[str]) -> Case:
    """Crea el expediente del perito con los datos del siniestro y las alertas de Evidex, y lo registra."""
    from evidex.investigations import dossier
    if derivation(case):
        raise ValueError("El caso ya está derivado. Anule la derivación vigente para derivarlo de nuevo.")
    if not empresa:
        raise ValueError("Elija la empresa de peritaje.")
    if plazo:
        date.fromisoformat(plazo)
    base = f"INV-{case.root.name}"
    cid, n = base, 2
    while (Path(workdir) / cid / "case.json").exists():
        cid, n = f"{base}-{n}", n + 1
    data = {"numero": decl.get("numero", case.root.name), "aseguradora": "", "tipo": "Vehículo",
            "direccion": decl.get("lugar", ""), "comuna": "", "vehiculo": decl.get("vehiculo", ""),
            "patente": decl.get("patente", ""), "rut_asegurado": decl.get("rut", ""),
            "descripcion": decl.get("descripcion", ""), "fecha_ocurrencia": decl.get("fecha_siniestro", ""),
            "alertas": alertas, "siniestro_id": case.root.name, "empresa": empresa, "perito": perito,
            "plazo": plazo, "instrucciones": instrucciones}
    inv = dossier.create(workdir, cid, data, [], [], actor=actor)
    case.ledger.append(actor, "case_derived", empresa, {"empresa": empresa, "perito": perito, "plazo": plazo,
                                                         "instrucciones": instrucciones, "dossier": cid})
    return inv


def cancel_derivation(case: Case, actor: str, reason: str) -> None:
    d = derivation(case)
    if not d:
        raise ValueError("El caso no tiene una derivación vigente.")
    case.ledger.append(actor, "derivation_cancelled", d["empresa"], {"reason": reason, "dossier": d["dossier"]})


def mark_delivered(case: Case, actor: str, dossier_id: str) -> None:
    d = derivation(case)
    if d and d.get("dossier") == dossier_id and not d.get("delivered"):
        case.ledger.append(actor, "derivation_delivered", d["empresa"], {"dossier": dossier_id})


# ---- actividad ---------------------------------------------------------------------------------
def last_activity(case: Case) -> datetime:
    """Último movimiento del caso (cualquier entrada de la cadena de custodia, salvo análisis automáticos).
    "veritas" es el nombre anterior del sistema y sigue apareciendo en casos antiguos."""
    ts = next((e["ts"] for e in reversed(case.ledger.entries()) if e["action"] != "claim_analyzed"
               and e["actor"] not in ("evidex", "veritas")), case.ledger.entries()[0]["ts"])
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def idle_days(case: Case) -> int:
    return (datetime.now(timezone.utc) - last_activity(case)).days


# ---- empresas de peritaje ----------------------------------------------------------------------
def firms(workdir: Path) -> list[dict]:
    try:
        return json.loads((Path(workdir) / "empresas.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def save_firm(workdir: Path, nombre: str, rut: str = "", contacto: str = "") -> str | None:
    nombre = " ".join(nombre.split())[:80]
    if len(nombre) < 3:
        return "Escriba el nombre de la empresa."
    items = [f for f in firms(workdir) if f["nombre"].lower() != nombre.lower()]
    items.append({"nombre": nombre, "rut": rut.strip(), "contacto": contacto.strip()})
    items.sort(key=lambda f: f["nombre"].lower())
    path = Path(workdir) / "empresas.json"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=workdir, delete=False, suffix=".tmp") as tmp:
        json.dump(items, tmp, ensure_ascii=False, indent=2)
    Path(tmp.name).replace(path)
    return None


# ---- ejemplo: equipo ficticio --------------------------------------------------------------
DEMO_ANALYSTS = [("camila.rojas", "Camila Rojas"), ("diego.munoz", "Diego Muñoz")]
DEMO_FIRM = "Investigaciones Andes (ejemplo)"


def seed_demo_team(workdir: Path, numeros: list[str], actor: str, me: tuple[str, str] | None = None) -> None:
    """Reparte los siniestros del ejemplo entre analistas ficticios y deriva dos a una empresa ficticia.

    Si quien carga el ejemplo es un analista (`me`), todos quedan a su nombre para que pueda verlos."""
    from datetime import timedelta
    from evidex.claims import service
    if not any(f["nombre"] == DEMO_FIRM for f in firms(workdir)):
        save_firm(workdir, DEMO_FIRM, "", "contacto@ejemplo.invalid")
    team = [me] if me else DEMO_ANALYSTS
    for i, numero in enumerate(numeros):
        case = service.find_case(workdir, numero)
        if case is None or owner(case):
            continue
        user, name = team[i % len(team)]
        assign(case, user, name, actor, "ejemplo")
    for numero, days in (("SIN-2026-0987", 10), ("SIN-2026-0601", -3)):
        case = service.find_case(workdir, numero)
        if case is None or derivation(case):
            continue
        decl = service.declaration(case) or {}
        alerts = [f["title"] for f in service.snapshot(case)["findings"] if f["severity"] in ("alta", "media")][:8]
        derive(workdir, case, decl, DEMO_FIRM, "", (date.today() + timedelta(days=days)).isoformat(),
               "Entrevistar al asegurado y al conductor. Confirmar el lugar del choque.", actor, alerts)
