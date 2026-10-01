"""Funciones compartidas por las vistas: acceso a la carpeta de casos, usuario actual y resúmenes.

El estado de la aplicación (carpeta de casos, usuarios, registro de siniestros) vive en
current_app.extensions["veritas"]; `cx` lo expone con nombres simples para no repetir esa ruta.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from flask import abort, current_app, g, request
from werkzeug.utils import secure_filename

from veritas.claims import service
from veritas.core.case import Case
from veritas.investigations import dossier as INV

FORM_FIELDS = ("numero", "poliza", "asegurado", "rut", "telefono", "email", "direccion", "cuenta_bancaria", "patente",
               "lugar", "taller", "testigos", "parte_policial", "fecha_denuncia", "inicio_poliza", "fin_poliza",
               "cambio_cobertura", "suma_asegurada", "deducible", "monto_reclamado", "descripcion")
LEVEL_TEXT = {"bad": "Derivar a investigación", "warn": "Revisión manual", "ok": "Sin alertas", "none": "Esperando evidencia"}
SAFE_ID = re.compile(r"[\w\-.]+")


class _Context:
    """Atajo de lectura al estado de la aplicación activa."""

    @property
    def _state(self) -> dict:
        return current_app.extensions["veritas"]

    @property
    def workdir(self) -> Path:
        return self._state["workdir"]

    @property
    def registry(self) -> Path:
        return self._state["registry"]

    @property
    def store(self):
        return self._state["store"]

    @property
    def config_path(self) -> Path:
        return self._state["workdir"] / "config.json"


cx = _Context()


def amount(v) -> int:
    digits = re.sub(r"[^0-9]", "", str(v or "").split(",")[0])
    return int(digits) if digits else 0


def actor_name() -> str:
    u = getattr(g, "user", None)
    return u["name"] if u else request.form.get("actor", "").strip()


def log_access(action, subject=""):
    u = getattr(g, "user", None)
    if u:
        cx.store.log(u["username"], action, subject, request.remote_addr or "")


def load_claim(cid: str) -> Case:
    if not SAFE_ID.fullmatch(cid):
        abort(404)
    case = Case(cx.workdir / cid)
    if not case.meta_path.exists() or case.kind != "claim":
        abort(404)
    return case


def summarize(case: Case) -> dict:
    decl = service.declaration(case) or {}
    last = service.last_analysis(case) or {}
    return {
        "id": case.root.name, "numero": decl.get("numero", case.root.name),
        "patente": decl.get("patente", "—"), "asegurado": decl.get("asegurado", "—"),
        "fecha": decl.get("fecha_siniestro", "").replace("T", " ")[:16],
        "photos": last.get("photos", "—"), "findings": last.get("findings", "—"),
        "score": last.get("score", "—"), "linked": last.get("linked", "—"),
        "decision": (dec := service.current_decision(case)) and dec["subject"],
        "decision_label": dec and dec["data"]["label"],
        "rec": last.get("recommendation", "Sin analizar"), "level": last.get("level", "none"),
        "analyzed": last.get("ts", "—").replace("T", " ").rstrip("Z")[:16] + " UTC" if last else "—",
        "created": case.ledger.entries()[0]["ts"],
        "monto": amount(decl.get("monto_reclamado")),
    }


def save_uploads(files, folder: Path) -> tuple[list[Path], list[str]]:
    saved, rejected, used = [], [], set()
    for fs in files:
        if not fs or not fs.filename:
            continue
        name = secure_filename(fs.filename) or "archivo"
        if Path(name).suffix.lower() not in service.whatsapp.CHAT_EXT and service.evidence_note(name) is None:
            rejected.append(fs.filename)
            continue
        base, n = name, 1
        while name.lower() in used:
            name = f"{Path(base).stem}_{n}{Path(base).suffix}"; n += 1
        used.add(name.lower())
        dest = folder / name
        fs.save(dest)
        if service.evidence_note(dest) is None:     # .txt o .zip que no es un chat exportado
            dest.unlink()
            rejected.append(fs.filename)
            continue
        saved.append(dest)
    return saved, rejected


def claim_list() -> list[dict]:
    cases = []
    for d in sorted(cx.workdir.iterdir()):
        if (d / "case.json").exists():
            c = Case(d)
            if c.kind == "claim":
                cases.append(summarize(c))
    # cola de trabajo: primero el mayor riesgo, luego los más recientes
    cases.sort(key=lambda c: c["created"], reverse=True)
    cases.sort(key=lambda c: c["score"] if isinstance(c["score"], int) else -1, reverse=True)
    return cases


def level_counts(cases):
    counts = {k: sum(1 for c in cases if c["level"] == k) for k in ("bad", "warn", "ok", "none")}
    counts["pend"] = sum(1 for c in cases if c["level"] == "bad" and c["decision"] in (None, "en_revision"))
    return counts


def network_components():
    from veritas.claims import analysis as _claims
    from veritas.forensics import network
    from veritas.claims.report import _net_svg
    comps = network.components(_claims.load_registry(cx.registry))
    for c in comps:
        for m in c["members"]:
            case = service.find_case(cx.workdir, m)
            dec = service.current_decision(case) if case else None
            last = service.last_analysis(case) if case else None
            c["info"][m].update({"id": case.root.name if case else service.case_id(m),
                                 "level": (last or {}).get("level", c["info"][m]["level"]),
                                 "decision": dec and dec["subject"], "decision_label": dec and dec["data"]["label"]})
        degree = {m: 0 for m in c["members"]}
        for a, b, _ in c["edges"]:
            degree[a] += 1
            degree[b] += 1
        hub = max(c["members"], key=lambda m: degree[m])
        c["svg"] = _net_svg({"center": hub, "group": [m for m in c["members"] if m != hub], "group_edges": c["edges"],
                             "group_info": {m: c["info"][m] for m in c["members"]}}, center_label="más conexiones")
    return comps


def public_base() -> str:
    """Dirección que recibe el asegurado: dominio configurado > túnel público > red local > este equipo."""
    cfg_url = (load_settings().get("direccion_publica") or "").strip().rstrip("/")
    if cfg_url.startswith("https://"):
        return cfg_url
    if current_app.config.get("PUBLIC") or current_app.config.get("LAN"):
        return current_app.config["PUBLIC_BASE"]
    return request.host_url.rstrip("/")


def load_settings() -> dict:
    try:
        return json.loads(cx.config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_dossier(cid: str, kind: str) -> Case:
    if not SAFE_ID.fullmatch(cid):
        abort(404)
    case = Case(cx.workdir / cid)
    if not case.meta_path.exists() or case.kind != kind:
        abort(404)
    return case


def dossier_lists():
    exps = []
    for c in INV.list_cases(cx.workdir, "investigacion"):
        a = INV.analyze(c)
        d = a["data"]
        exps.append({"id": c.root.name, "numero": d.get("numero"), "aseguradora": d.get("aseguradora", ""),
                     "fecha": (d.get("fecha_ocurrencia") or "").replace("T", " ")[:16], "interviews": len(a["interviews"]),
                     "findings": len(a["findings"]), "alerts": len(d.get("alertas", [])),
                     "answered": sum(1 for r in a["responses"].values() if r.get("estado")), "pending": len(INV.review(a))})
    audits = []
    for c in INV.list_cases(cx.workdir, "auditoria"):
        run = next((e for e in reversed(c.ledger.entries()) if e["action"] == "audit_run"), None)
        first = c.ledger.entries()[0]
        audits.append({"id": c.root.name, "name": run["subject"] if run else c.name, "ts": first["ts"][:16].replace("T", " "),
                       "actor": first["actor"], **(run["data"] if run else {"alta": 0, "media": 0, "baja": 0})})
    return exps, audits


def portal_case(token):
    from veritas.portal import links as capture
    case, data = capture.find(cx.workdir, token)
    if not case:
        abort(404)
    return case, data
