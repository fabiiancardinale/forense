"""Inicio según el rol, y panel de equipo del jefe (carga, atrasos, resultados y reasignación)."""
from __future__ import annotations

from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from evidex.claims import assignment
from evidex.core.case import Case
from evidex.web.common import (SAFE_ID, actor_name, analysts, claim_list, current_user, cx, dossier_lists, has_perm,
                                level_counts, log_access, network_components, sees_all_claims)

bp = Blueprint("panel", __name__)
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre",
          "diciembre"]
OPEN = (None, "en_revision")


def _today() -> str:
    t = date.today()
    return f"{t.day} de {MONTHS[t.month - 1]} de {t.year}"


@bp.get("/")
def dashboard():
    u = current_user()
    if u and u["role"] == "perito":
        return redirect(url_for("investigations.investigations"))
    cases = claim_list()
    counts = level_counts(cases)
    undecided = [c for c in cases if c["decision"] in OPEN]
    comps = network_components() if cases and has_perm("redes") else []
    exps, audits = dossier_lists() if has_perm("peritaje") else ([], [])
    k = {"pend_bad": counts["pend"],
         "pend_warn": sum(1 for c in undecided if c["level"] == "warn"),
         "rings": sum(1 for c in comps if len(c["members"]) >= 3),
         "pairs": sum(1 for c in comps if len(c["members"]) == 2),
         "involved": sum(len(c["members"]) for c in comps),
         "monto_pend": sum(c["monto"] for c in undecided if c["level"] == "bad"),
         "fraude": sum(1 for c in cases if c["decision"] == "fraude"),
         "legitimo": sum(1 for c in cases if c["decision"] == "legitimo"),
         "sin_decision": len(undecided)}
    priority = [c for c in undecided if c["level"] in ("bad", "warn")][:10]
    expert = sorted((c for c in cases if c["derivation"] and not c["derivation"]["delivered"]),
                    key=lambda c: c["derivation"].get("plazo") or "9999")
    mine = bool(u and not sees_all_claims())
    return render_template("panel/dashboard.html", cases=cases, counts=counts, k=k, priority=priority, comps=comps,
                           waiting=_waiting(cases)[:8], expert=expert[:8], expedientes=exps, audits=audits,
                           today=_today(), mine=mine, active="dash")


def _waiting(cases):
    from evidex.portal import links
    out = []
    for c in cases:
        if c["portal"] not in ("enviado", "abierto", "vencido"):
            continue
        cc = Case(cx.workdir / c["id"])
        data = links.load(cc)
        pr = links.progress(data, cc.excluded())
        out.append({**c, "pct": pr["pct"], "done": pr["done"], "total": pr["total"], "opened": data.get("opened"),
                    "expired": c["portal"] == "vencido",
                    "days": (datetime.now() - datetime.fromisoformat(data["created"])).days})
    out.sort(key=lambda w: (w["expired"], -w["days"]))
    return out


# ---- equipo --------------------------------------------------------------------------------------
def _late_reasons(c) -> list[str]:
    out = []
    d = c["derivation"]
    if d and d["state"] == "atrasado":
        late = (date.today() - date.fromisoformat(d["plazo"])).days
        out.append(f"Peritaje de {d['empresa']} atrasado {late} día(s)")
    if c["portal"] == "vencido":
        out.append("Enlace del asegurado vencido")
    if c["decision"] in OPEN and c["idle"] >= assignment.STALE_DAYS:
        out.append(f"Sin movimiento hace {c['idle']} días")
    return out


@bp.get("/equipo")
def team():
    cases = claim_list(everyone=True)
    for c in cases:
        c["late"] = _late_reasons(c)
    people: dict[str, dict] = {a["username"]: {"user": a["username"], "name": a["name"]} for a in analysts()}
    for c in cases:
        key = c["owner"] or ""
        people.setdefault(key, {"user": key, "name": c["owner_name"] if key else "Sin asignar"})
    rows = []
    for key, p in people.items():
        mine = [c for c in cases if (c["owner"] or "") == key]
        open_ = [c for c in mine if c["decision"] in OPEN]
        rows.append({**p, "total": len(mine), "open": len(open_),
                     "high": sum(1 for c in open_ if c["level"] == "bad"),
                     "waiting": sum(1 for c in open_ if c["portal"] in ("enviado", "abierto")),
                     "derived": sum(1 for c in open_ if c["derivation"] and not c["derivation"]["delivered"]),
                     "late": sum(1 for c in open_ if c["late"]),
                     "closed": len(mine) - len(open_),
                     "fraud": sum(1 for c in mine if c["decision"] == "fraude"),
                     "fraud_amount": sum(c["monto"] for c in mine if c["decision"] == "fraude"),
                     "legit": sum(1 for c in mine if c["decision"] == "legitimo")})
    rows = [r for r in rows if r["total"] or r["user"]]
    rows.sort(key=lambda r: (r["user"] == "", -r["open"], r["name"].lower()))
    late = sorted((c for c in cases if c["late"] and c["decision"] in OPEN), key=lambda c: -c["idle"])
    open_cases = [c for c in cases if c["decision"] in OPEN]
    k = {"open": len(open_cases), "late": len(late), "fraud": sum(r["fraud"] for r in rows),
         "fraud_amount": sum(r["fraud_amount"] for r in rows), "unassigned": sum(1 for c in open_cases if not c["owner"])}
    return render_template("panel/team.html", rows=rows, top=max((r["open"] for r in rows), default=0) or 1, late=late,
                           firms=_firm_results(cases), k=k, open_cases=open_cases, team=analysts(), today=_today(),
                           stale=assignment.STALE_DAYS, active="team")


def _firm_results(cases) -> list[dict]:
    """Por empresa de peritaje: derivados, entregados, atrasados, días promedio de entrega y fraudes confirmados."""
    out: dict[str, dict] = {}
    for c in cases:
        d = c["derivation"]
        if not d:
            continue
        r = out.setdefault(d["empresa"], {"empresa": d["empresa"], "derived": 0, "delivered": 0, "late": 0, "days": [],
                                          "fraud": 0, "fraud_amount": 0})
        r["derived"] += 1
        if d["delivered"]:
            r["delivered"] += 1
            r["days"].append((datetime.fromisoformat(d["delivered"].rstrip("Z")) -
                              datetime.fromisoformat(d["ts"].rstrip("Z"))).days)
        if d["state"] == "atrasado":
            r["late"] += 1
        if c["decision"] == "fraude":
            r["fraud"] += 1
            r["fraud_amount"] += c["monto"]
    for r in out.values():
        r["avg_days"] = round(sum(r["days"]) / len(r["days"]), 1) if r["days"] else None
    return sorted(out.values(), key=lambda r: -r["derived"])


@bp.post("/equipo/reasignar")
def reassign():
    """Reasigna uno o varios casos a otro analista; queda en la cadena de custodia de cada caso."""
    cids = request.form.getlist("cid")
    motivo = request.form.get("motivo", "").strip()[:200]
    target = request.form.get("analista", "").strip()
    person = next((a for a in analysts() if a["username"] == target), None)
    if person is None and not cx.store.enabled():
        name = request.form.get("analista_nombre", "").strip()
        person = {"username": name.lower().replace(" ", "."), "name": name} if name else None
    back = (url_for("claims.case_view", cid=cids[0]) if request.form.get("volver") == "caso" and cids
            else url_for("panel.team"))
    if not cids or not person:
        flash("Elija los casos y el analista.", "bad")
        return redirect(back)
    moved = 0
    for cid in cids:
        if not SAFE_ID.fullmatch(cid):
            continue
        case = Case(cx.workdir / cid)
        if not case.meta_path.exists() or case.kind != "claim":
            continue
        o = assignment.owner(case)
        if o and o["user"] == person["username"]:
            continue
        assignment.assign(case, person["username"], person["name"], actor_name() or "jefe", motivo)
        moved += 1
    log_access("reasignar", f"{moved} caso(s) a {person['name']}")
    flash(f"{moved} caso(s) reasignado(s) a {person['name']}." if moved else "No hubo cambios.", "ok" if moved else "info")
    return redirect(back)
