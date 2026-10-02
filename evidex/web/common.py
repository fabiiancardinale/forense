"""Funciones compartidas por las vistas: acceso a la carpeta de casos, usuario actual y resúmenes.

El estado de la aplicación (carpeta de casos, usuarios, registro de siniestros) vive en
current_app.extensions["evidex"]; `cx` lo expone con nombres simples para no repetir esa ruta.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from flask import abort, current_app, g, request, send_file
from werkzeug.utils import secure_filename

from evidex.accounts import users as U
from evidex.claims import assignment, service
from evidex.core.case import Case
from evidex.investigations import dossier as INV

FORM_FIELDS = ("numero", "poliza", "asegurado", "rut", "telefono", "email", "direccion", "cuenta_bancaria", "patente",
               "lugar", "taller", "testigos", "parte_policial", "fecha_denuncia", "inicio_poliza", "fin_poliza",
               "cambio_cobertura", "suma_asegurada", "deducible", "monto_reclamado", "descripcion")
LEVEL_TEXT = {"bad": "Derivar a investigación", "warn": "Revisión manual", "ok": "Sin alertas", "none": "Esperando evidencia"}
SAFE_ID = re.compile(r"[\w\-.]+")


class _Context:
    """Atajo de lectura al estado de la aplicación activa."""

    @property
    def _state(self) -> dict:
        return current_app.extensions["evidex"]

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


# ---- usuario actual y acceso a casos ------------------------------------------------------------
def current_user() -> dict | None:
    return getattr(g, "user", None)


def has_perm(perm: str) -> bool:
    """En modo demo (sin usuarios) todo está permitido."""
    u = current_user()
    return not cx.store.enabled() or (u is not None and U.can(u["role"], perm))


def sees_all_claims() -> bool:
    return has_perm("ver_todos")


def claim_visible(case: Case) -> bool:
    """Un analista solo ve sus casos; jefe, administrador e investigador ven todos."""
    if sees_all_claims():
        return True
    o, u = assignment.owner(case), current_user()
    return bool(o and u and o["user"] == u["username"])


def dossier_visible(case: Case) -> bool:
    """Un perito solo ve los expedientes derivados a su empresa (y a él, si se nombró a un perito)."""
    if has_perm("investigaciones"):
        return True
    u = current_user()
    if not u or u["role"] != "perito":
        return False
    data = INV.load(case)["data"]
    return (data.get("empresa", "").lower() == (u.get("empresa") or "").lower()
            and data.get("perito") in ("", None, u["username"]))


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
    if not case.meta_path.exists() or case.kind != "claim" or not claim_visible(case):
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
        **_work_state(case),
    }


def _work_state(case: Case) -> dict:
    """Quién lo tiene, en qué está y hace cuánto no se mueve."""
    from evidex.portal import links
    o = assignment.owner(case)
    d = assignment.derivation(case)
    cap = links.load(case)
    portal = None
    if cap:
        portal = ("recibido" if cap.get("finished") else "vencido" if links.status(cap) else
                  "abierto" if cap.get("opened") else "enviado")
    return {"owner": o["user"] if o else None,
            "owner_name": ((cx.store.get(o["user"]) or {}).get("name") or o["name"]) if o else "Sin asignar",
            "derivation": d, "portal": portal, "idle": assignment.idle_days(case)}


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


def claim_list(everyone: bool = False) -> list[dict]:
    """Siniestros visibles para el usuario actual (todos, con `everyone`, si tiene permiso)."""
    cases = []
    for d in sorted(cx.workdir.iterdir()):
        if (d / "case.json").exists():
            c = Case(d)
            if c.kind == "claim" and ((everyone and sees_all_claims()) or claim_visible(c)):
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
    from evidex.claims import analysis as _claims
    from evidex.forensics import network
    from evidex.claims.report import _net_svg
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
    if not case.meta_path.exists() or case.kind != kind or (kind == "investigacion" and not dossier_visible(case)):
        abort(404)
    return case


def dossier_lists():
    exps = []
    for c in INV.list_cases(cx.workdir, "investigacion"):
        if not dossier_visible(c):
            continue
        a = INV.analyze(c)
        d = a["data"]
        exps.append({"id": c.root.name, "numero": d.get("numero"), "aseguradora": d.get("aseguradora", ""),
                     "empresa": d.get("empresa", ""), "plazo": d.get("plazo", ""), "siniestro_id": d.get("siniestro_id"),
                     "delivered": INV.delivered(c),
                     "fecha": (d.get("fecha_ocurrencia") or "").replace("T", " ")[:16], "interviews": len(a["interviews"]),
                     "findings": len(a["findings"]), "alerts": len(d.get("alertas", [])),
                     "answered": sum(1 for r in a["responses"].values() if r.get("estado")), "pending": len(INV.review(a))})
    audits = []
    for c in (INV.list_cases(cx.workdir, "auditoria") if has_perm("investigaciones") else []):
        run = next((e for e in reversed(c.ledger.entries()) if e["action"] == "audit_run"), None)
        first = c.ledger.entries()[0]
        audits.append({"id": c.root.name, "name": run["subject"] if run else c.name, "ts": first["ts"][:16].replace("T", " "),
                       "actor": first["actor"], **(run["data"] if run else {"alta": 0, "media": 0, "baja": 0})})
    return exps, audits


def portal_case(token):
    from evidex.portal import links as capture
    case, data = capture.find(cx.workdir, token)
    if not case:
        abort(404)
    return case, data


def analysts() -> list[dict]:
    """Personas que pueden tener casos: usuarios analistas (y jefes), o en modo demo, los nombres ya usados."""
    if cx.store.enabled():
        return [{"username": u["username"], "name": u["name"]} for u in cx.store.by_role("analista", "jefe")]
    seen = {}
    for d in sorted(cx.workdir.iterdir()):
        if (d / "case.json").exists() and Case(d).kind == "claim":
            o = assignment.owner(Case(d))
            if o:
                seen[o["user"]] = o["name"]
    return [{"username": k, "name": v} for k, v in sorted(seen.items(), key=lambda kv: kv[1].lower())]


MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".pdf": "application/pdf", ".webp": "image/webp"}


def send_evidence(case: Case, digest: str, mini: bool = False):
    """Entrega un archivo de evidencia tal cual (o una miniatura JPEG). Las fotos HEIC se convierten para verlas."""
    import io
    if not re.fullmatch(r"[0-9a-f]{64}", digest or "") or not service.has_evidence(case, digest):
        abort(404)
    path = case.evidence_dir / digest
    name = next((e["data"]["original_name"] for e in case.ledger.entries()
                 if e["action"] == "evidence_added" and e["subject"] == digest), "archivo")
    ext = Path(name).suffix.lower()
    if mini or ext in (".heic", ".heif"):
        try:
            from PIL import Image, ImageOps
            with Image.open(path) as img:
                img = ImageOps.exif_transpose(img).convert("RGB")
                if mini:
                    img.thumbnail((360, 360))
                buf = io.BytesIO()
                img.save(buf, "JPEG", quality=82)
            return send_file(io.BytesIO(buf.getvalue()), mimetype="image/jpeg", max_age=3600)
        except Exception:
            if mini:
                abort(404)
    mime = MIME.get(ext, "application/octet-stream")
    log_access("ver_archivo", name)
    return send_file(path, mimetype=mime, download_name=name, as_attachment=mime == "application/octet-stream")
