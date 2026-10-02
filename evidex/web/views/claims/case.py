"""Ficha del caso, organizada en pestañas para que cada cosa tenga un lugar fijo:

  resumen     qué falta por hacer, alertas principales, datos del siniestro y decisión
  fotos       todas las fotos (del asegurado y del analista) con sus alertas
  documentos  PDF, documentos fotografiados y chats, con sus alertas
  peritaje    derivación a una empresa de peritaje, entrevistas e informe final
  asegurado   portal del asegurado: enlace, avance y lo que subió
  informe     informe completo de Evidex, verificación y paquete verificable
  historial   cadena de custodia, asignaciones y accesos
"""
from __future__ import annotations

import io
import json
import os
import tempfile
from pathlib import Path

from flask import abort, flash, redirect, render_template, request, send_file, url_for

from evidex.claims import assignment, service
from evidex.claims.guide import for_rule
from evidex.claims.report import ACTIONS
from evidex.core import export
from evidex.core.case import Case
from evidex.core.ledger import verify_chain, verify_seal
from evidex.web.common import (actor_name, analysts, cx, has_perm, load_claim, load_settings, log_access, summarize)
from evidex.web.views.claims import bp

TABS = [("resumen", "Resumen"), ("fotos", "Fotos"), ("documentos", "Documentos"), ("peritaje", "Peritaje"),
        ("asegurado", "Asegurado"), ("informe", "Informe"), ("historial", "Historial")]
SEV_ORDER = {"alta": 0, "media": 1, "baja": 2}
KIND_LABEL = {"foto": "Foto", "documento": "Documento", "chat": "Chat de WhatsApp"}


def _refresh_if_needed(case: Case) -> None:
    """Reanaliza si no hay informe o si cambió la evidencia (llegó algo del portal, se quitó un archivo)."""
    n_ev = sum(1 for e in case.ledger.entries()
               if e["action"] in ("evidence_added", "evidence_excluded", "evidence_restored"))
    mark = case.root / "informe.evidencias"
    try:
        seen = int(mark.read_text())
    except (OSError, ValueError):
        seen = -1
    if not (case.root / "informe.html").exists() or not (case.root / service.SNAPSHOT).exists() or seen != n_ev:
        service.analyze_claim(case, cx.registry)
        mark.write_text(str(n_ev))


def evidence_items(case: Case, snap: dict) -> list[dict]:
    """Todos los archivos del caso (también los quitados del análisis), con sus datos y alertas."""
    excluded = case.excluded()
    photos = {p["digest"]: p for p in snap["photos"]}
    docs = {d["digest"]: d for d in snap["docs"]}
    by_ev: dict[str, list[dict]] = {}
    for f in snap["findings"]:
        for ev in f["evidence"]:
            by_ev.setdefault(ev, []).append(f)
    items = []
    for e in case.ledger.entries():
        if e["action"] != "evidence_added" or e["data"].get("note") == "declaracion":
            continue
        d, digest = e["data"], e["subject"]
        note = d.get("note") or ("documento" if Path(d["original_name"]).suffix.lower() == ".pdf" else "foto")
        info = photos.get(digest) or docs.get(digest) or {}
        found = sorted(by_ev.get(digest[:8], []), key=lambda f: SEV_ORDER[f["severity"]])
        items.append({
            "digest": digest, "kind": note, "kind_label": KIND_LABEL.get(note, note.capitalize()),
            "title": (d.get("portal") or {}).get("title") or info.get("title") or d["original_name"],
            "name": d["original_name"], "who": "asegurado" if e["actor"].startswith("asegurado") else e["actor"],
            "received": e["ts"], "info": info, "findings": found,
            "worst": found[0]["severity"] if found else None, "excluded": excluded.get(digest),
            "is_image": Path(d["original_name"]).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"),
        })
    return items


@bp.get("/caso/<cid>")
def case_view(cid):
    case = load_claim(cid)
    tab = request.args.get("tab", "resumen")
    if tab not in dict(TABS):
        abort(404)
    _refresh_if_needed(case)
    c = summarize(case)
    log_access("ver_caso", c["numero"])
    snap = service.snapshot(case)
    items = evidence_items(case, snap)
    ctx = {"c": c, "tab": tab, "tabs": TABS, "active": "index",
           "n_photos": sum(1 for i in items if i["kind"] == "foto" and not i["excluded"]),
           "n_docs": sum(1 for i in items if i["kind"] != "foto" and not i["excluded"]),
           "n_findings": len(snap["findings"])}
    builder = {"resumen": _tab_summary, "fotos": _tab_photos, "documentos": _tab_docs, "peritaje": _tab_expert,
               "asegurado": _tab_portal, "informe": lambda case, snap, items: {}, "historial": _tab_history}[tab]
    ctx.update(builder(case, snap, items))
    return render_template("claims/case.html", **ctx)


def _tab_summary(case, snap, items):
    decl = service.declaration(case) or {}
    findings = sorted(snap["findings"], key=lambda f: SEV_ORDER[f["severity"]])
    thumbs = {i["digest"][:8]: i for i in items if i["is_image"]}
    top = []
    for f in findings[:6]:
        ref = next((thumbs[e] for e in f["evidence"] if e in thumbs), None)
        top.append({**f, "ref": ref, "guide": for_rule(f["rule"])})
    return {"decl": decl, "top": top, "decisions": service.DECISIONS, "history": service.decision_history(case),
            "todo": _todo(case, items), "team": analysts() if has_perm("equipo") else [],
            "can_reassign": has_perm("equipo")}


def _todo(case, items) -> list[tuple[str, str, str]]:
    """Próximos pasos sugeridos: (nivel, texto, pestaña)."""
    from evidex.portal import links
    out = []
    cap = links.load(case)
    d = assignment.derivation(case)
    c = summarize(case)
    if not items and not cap:
        out.append(("warn", "No hay fotos ni documentos: envíe el enlace al asegurado.", "asegurado"))
    if cap and not cap.get("finished"):
        out.append(("warn" if links.status(cap) else "info",
                    "El enlace del asegurado venció sin que terminara: renuévelo." if links.status(cap)
                    else "Esperando que el asegurado termine de subir sus antecedentes.", "asegurado"))
    if c["level"] == "bad" and not d:
        out.append(("bad", "Riesgo alto: derive las entrevistas a una empresa de peritaje.", "peritaje"))
    if d and d["state"] == "atrasado":
        out.append(("bad", f"El peritaje de {d['empresa']} está atrasado (plazo {d['plazo']}).", "peritaje"))
    if d and d["state"] in ("derivado", "en_curso"):
        out.append(("info", f"Esperando el informe de {d['empresa']} (plazo {d.get('plazo') or 'sin plazo'}).", "peritaje"))
    if d and d["state"] == "entregado" and c["decision"] in (None, "en_revision"):
        out.append(("info", "El perito entregó su informe final: revíselo y registre la decisión.", "peritaje"))
    if not d and c["level"] != "bad" and c["decision"] in (None, "en_revision") and items:
        out.append(("info", "Revise las alertas y registre la decisión.", "resumen"))
    return out


def _tab_photos(case, snap, items):
    return {"items": [i for i in items if i["kind"] == "foto"]}


def _tab_docs(case, snap, items):
    return {"items": [i for i in items if i["kind"] != "foto"]}


def _tab_expert(case, snap, items):
    from datetime import date, timedelta
    from evidex.investigations import dossier
    d = assignment.derivation(case)
    prog = None
    if d:
        d["perito_name"] = cx.store.display_name(d.get("perito")) if d.get("perito") else ""
        inv = Case(cx.workdir / d["dossier"])
        prog = dossier.progress(inv) if inv.meta_path.exists() else None
    peritos = [u for u in cx.store.by_role("perito")] if cx.store.enabled() else []
    return {"der": d, "prog": prog, "firms": assignment.firms(cx.workdir), "peritos": peritos,
            "default_due": (date.today() + timedelta(days=10)).isoformat(),
            "alerts": sorted(snap["findings"], key=lambda f: SEV_ORDER[f["severity"]]),
            "past": [e for e in case.ledger.entries() if e["action"] in ("case_derived", "derivation_cancelled",
                                                                         "derivation_delivered")]}


def _tab_portal(case, snap, items):
    import base64
    import urllib.parse as up
    from flask import current_app
    from evidex.portal import links, tunnel
    from evidex.portal.links import DEFAULT_DOCS, DOC_TYPES
    from evidex.web.common import public_base
    cap = links.load(case)
    out = {"cap": cap, "doc_types": DOC_TYPES, "default_docs": DEFAULT_DOCS, "cap_lan": current_app.config.get("LAN", False)}
    if not cap:
        return out
    c = summarize(case)
    cap_url = f"{public_base()}/c/{cap['token']}"
    png = links.qr_png(cap_url)
    decl = service.declaration(case) or {}
    share = links.share_message(c["numero"], decl.get("asegurado", ""), cap_url, cap["expires"],
                                load_settings().get("empresa", ""))
    wa = mail = None
    if num := links.wa_number(decl.get("telefono", "")):
        wa = f"https://wa.me/{num}?text={up.quote(share)}"
    if decl.get("email"):
        mail = (f"mailto:{decl['email']}?subject={up.quote('Siniestro ' + c['numero'] + ': fotos y documentos')}"
                f"&body={up.quote(share)}")
    out.update(cap_url=cap_url, cap_qr=base64.b64encode(png).decode() if png else None, share_msg=share,
               wa_url=wa, mail_url=mail, pr=links.progress(cap, case.excluded()),
               cap_state="Vencido" if links.status(cap) and not cap.get("finished") else None,
               cap_local=tunnel.is_local(cap_url))
    return out


def _tab_history(case, snap, items):
    rows = []
    for e in case.ledger.entries():
        d = e.get("data") or {}
        what = ACTIONS.get(e["action"], e["action"])
        detail = {"evidence_added": (d.get("portal") or {}).get("title") or d.get("original_name", ""),
                  "case_assigned": d.get("name", e["subject"]) + (f" ({d['reason']})" if d.get("reason") else ""),
                  "case_derived": f"{d.get('empresa', '')}, plazo {d.get('plazo') or 'sin plazo'}",
                  "derivation_cancelled": d.get("reason", ""), "decision": d.get("label", ""),
                  "evidence_excluded": d.get("reason", ""),
                  "claim_analyzed": f"{d.get('findings', 0)} hallazgo(s), riesgo {d.get('score', '—')}"}.get(e["action"], "")
        rows.append({"ts": e["ts"], "actor": e["actor"], "what": what, "detail": detail, "hash": e["hash"]})
    return {"rows": rows[::-1], "accesos": cx.store.entries(subject=summarize(case)["numero"], limit=50) if cx.store.enabled() else []}


# ---- acciones del caso ----------------------------------------------------------------------------
@bp.get("/caso/<cid>/informe")
def report(cid):
    case = load_claim(cid)
    return send_file(case.root / "informe.html", mimetype="text/html")


@bp.post("/caso/<cid>/analizar")
def reanalyze(cid):
    r = service.analyze_claim(load_claim(cid), cx.registry)
    flash(f"Análisis actualizado: {r['findings']} hallazgo(s). {r['recommendation']}.", "info")
    if r.get("reanalyzed"):
        flash("También se reanalizaron los siniestros vinculados: " + ", ".join(r["reanalyzed"]) + ".", "info")
    return redirect(url_for("claims.case_view", cid=cid, tab=request.form.get("tab") or None))


@bp.post("/caso/<cid>/verificar")
def verify(cid):
    case = load_claim(cid)
    entries = case.ledger.entries()
    chain_ok, chain_msg = verify_chain(entries)
    ev_ok, problems = case.verify_evidence()
    seal_path = case.root / "seal.json"
    seal_ok, seal_msg = (verify_seal(entries, json.loads(seal_path.read_text(encoding="utf-8")),
                                     case.ledger.pub_path.read_bytes())
                         if seal_path.exists() else (False, "sin firma"))
    if chain_ok and ev_ok and seal_ok:
        flash(f"Integridad verificada: {chain_msg}, hashes de evidencia coinciden, firma digital válida.", "ok")
    else:
        detail = [m for ok, m in [(chain_ok, chain_msg), (seal_ok, seal_msg)] if not ok] + problems
        flash("Problema de integridad: " + "; ".join(detail), "bad")
    return redirect(url_for("claims.case_view", cid=cid, tab="informe"))


@bp.get("/caso/<cid>/exportar")
def export_zip(cid):
    log_access("descarga", f"paquete verificable {cid}")
    case = load_claim(cid)
    html = (case.root / "informe.html").read_text(encoding="utf-8")
    fd, tmp = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        export.export_bundle(case, html, Path(tmp))
        data = io.BytesIO(Path(tmp).read_bytes())
    finally:
        os.unlink(tmp)
    return send_file(data, mimetype="application/zip", as_attachment=True, download_name=f"{cid}_evidex.zip")


@bp.post("/caso/<cid>/decision")
def decide(cid):
    case = load_claim(cid)
    value, actor = request.form.get("decision", ""), actor_name()
    if value not in service.DECISIONS or not actor:
        flash("Indique la decisión y su nombre.", "bad")
    else:
        service.set_decision(case, value, actor, request.form.get("nota", "").strip())
        log_access("decision", (service.declaration(case) or {}).get("numero", cid))
        flash(f"Decisión registrada: {service.DECISIONS[value]}.", "ok")
    return redirect(url_for("claims.case_view", cid=cid))
