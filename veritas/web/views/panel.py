"""Panel de inicio."""
from __future__ import annotations


from flask import Blueprint, render_template

from veritas.core.case import Case
from veritas.web.common import claim_list, cx, dossier_lists, level_counts, network_components

bp = Blueprint("panel", __name__)


@bp.get("/")
def dashboard():
    from datetime import date
    cases = claim_list()
    counts = level_counts(cases)
    undecided = [c for c in cases if c["decision"] in (None, "en_revision")]
    comps = network_components() if cases else []
    exps, audits = dossier_lists()
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
    from veritas.portal import links as capture
    from datetime import datetime as _dt
    waiting = []
    for c in cases:
        cc = Case(cx.workdir / c["id"])
        data = capture.load(cc)
        if data and not data.get("finished"):
            pr = capture.progress(data, cc.excluded())
            waiting.append({**c, "pct": pr["pct"], "done": pr["done"], "total": pr["total"], "opened": data.get("opened"),
                            "expired": _dt.now() > _dt.fromisoformat(data["expires"]),
                            "days": (_dt.now() - _dt.fromisoformat(data["created"])).days})
    waiting.sort(key=lambda w: (w["expired"], -w["days"]))
    months = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
              "octubre", "noviembre", "diciembre"]
    t = date.today()
    return render_template("panel/dashboard.html", cases=cases, counts=counts, k=k, priority=priority, comps=comps,
                           waiting=waiting[:8], expedientes=exps, audits=audits, today=f"{t.day} de {months[t.month - 1]} de {t.year}",
                           active="dash")
