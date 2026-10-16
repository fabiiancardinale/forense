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
from evidex.claims.report import ACTIONS
from evidex.core import export
from evidex.core.case import Case
from evidex.core.ledger import verify_chain, verify_seal
from evidex.claims import comments
from evidex.web.common import (actor_name, current_user, analysis_mark, analysts, cx, has_perm, load_claim, load_settings,
                               log_access, needs_analysis, run_claim_analysis, summarize)
from evidex.web.views.claims import bp

TABS = [("resumen", "Resumen"), ("fotos", "Fotos"), ("documentos", "Documentos"), ("linea", "Línea de tiempo"), ("peritaje", "Peritaje"),
        ("asegurado", "Asegurado"), ("comentarios", "Comentarios"), ("informe", "Informe"), ("historial", "Historial")]
SEV_ORDER = {"alta": 0, "media": 1, "baja": 2}
PAIR_RULES = {"changed_between_versions", "damage_differs_between_photos", "ai_edit_of_original", "copy_of_ai_photo",
              "photo_differs_from_video"}
KIND_LABEL = {"foto": "Foto", "documento": "Documento", "chat": "Chat de WhatsApp", "audio": "Audio", "word": "Word",
              "video": "Video"}


def _refresh_if_needed(case: Case) -> None:
    """Reanaliza si no hay informe, si cambió la evidencia (llegó algo del portal, se quitó un archivo) o si
    Evidex trae pruebas nuevas. En segundo plano, la página abre igual con el análisis anterior."""
    from evidex.web import background
    if background.is_running(case) or not needs_analysis(case):
        return
    st = background.status(case)
    if st.get("state") == "failed" and st.get("mark") == analysis_mark(case):
        return                       # ya falló con esta misma evidencia: no reintentar solo, se usa "Reanalizar"
    run_claim_analysis(case)


def evidence_items(case: Case, snap: dict) -> list[dict]:
    """Todos los archivos del caso (también los quitados del análisis), con sus datos y alertas."""
    excluded = case.excluded()
    purged = case.purged()
    photos = {p["digest"]: p for p in snap["photos"]}
    docs = {d["digest"]: d for d in snap["docs"]}
    by_ev: dict[str, list[dict]] = {}
    for f in snap["findings"]:
        for ev in f["evidence"]:
            by_ev.setdefault(ev, []).append(f)
    from evidex.forensics.image_content import AI_CONFIRMED, zones
    try:
        import json
        content = json.loads((case.root / "analisis_imagen.json").read_text(encoding="utf-8"))
        content = content if isinstance(content, dict) else {}
    except (OSError, ValueError):
        content = {}
    from evidex.forensics.training_bank import Bank
    marked = {b["digest"]: b for b in Bank(cx.workdir).entries()}
    items = []
    for e in case.ledger.entries():
        if e["action"] != "evidence_added" or e["data"].get("note") == "declaracion":
            continue
        d, digest = e["data"], e["subject"]
        if digest in purged:
            continue                                   # eliminado definitivamente: solo queda en el historial
        note = d.get("note") or ("documento" if Path(d["original_name"]).suffix.lower() == ".pdf" else "foto")
        info = photos.get(digest) or docs.get(digest) or {}
        found = sorted(by_ev.get(digest[:8], []), key=lambda f: SEV_ORDER[f["severity"]])
        items.append({
            "digest": digest, "kind": note, "kind_label": KIND_LABEL.get(note, note.capitalize()),
            "title": (d.get("portal") or {}).get("title") or info.get("title") or d["original_name"],
            "name": d["original_name"], "who": "asegurado" if e["actor"].startswith("asegurado") else e["actor"],
            "from_word": d.get("word_name"),
            "word_image": (d.get("word_image") or _word_image(case, d, digest)) if d.get("from_word") else None,
            "received": e["ts"], "info": info, "findings": found,
            "zones": zones(content.get(digest) if isinstance(content.get(digest), dict) else {},
                           confirmed=any(f["rule"] in AI_CONFIRMED for f in found)),
            "worst": found[0]["severity"] if found else None, "excluded": excluded.get(digest),
            "model": (content.get(digest) or {}).get("learned") if isinstance(content.get(digest), dict) else None,
            "bank": marked.get(digest),
            "is_image": Path(d["original_name"]).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"),
        })
    return items


def _word_image(case, d, digest) -> dict:
    from evidex.forensics import word
    return word.details_for_image(case.evidence_dir / d["from_word"], digest)


@bp.post("/caso/<cid>/empresa")
def set_client(cid):
    """El administrador cambia la empresa cliente de un siniestro (queda en la cadena de custodia)."""
    from evidex.accounts import clients
    case = load_claim(cid)
    slug = request.form.get("cliente", "").strip() or None
    if slug and slug not in clients.all_clients(cx.workdir):
        abort(400)
    clients.set_case(case, slug, actor_name() or "administrador")
    log_access("usuario", f"{cid} → {clients.name_of(cx.workdir, slug)}")
    flash(f"El siniestro quedó en {clients.name_of(cx.workdir, slug)}.", "ok")
    return redirect(url_for("claims.case_view", cid=cid))


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
    from evidex.web import background
    ctx = {"c": c, "tab": tab, "tabs": TABS, "active": "index",
           "analyzing": background.is_running(case), "analysis_state": background.status(case),
           "n_photos": sum(1 for i in items if i["kind"] in ("foto", "video") and not i["excluded"]),
           "n_docs": sum(1 for i in items if i["kind"] not in ("foto", "video") and not i["excluded"]),
           "n_findings": len(snap["findings"]), "n_comments": comments.count(case), **_overview(case, c, snap, items),
           "decisions": service.DECISIONS, "history": service.decision_history(case),
           "client_choices": __import__("evidex.accounts.clients", fromlist=["x"]).all_clients(cx.workdir) if has_perm("admin") else {}}
    builder = {"resumen": _tab_summary, "fotos": _tab_photos, "documentos": _tab_docs, "peritaje": _tab_expert,
               "asegurado": _tab_portal, "informe": lambda case, snap, items: {}, "historial": _tab_history,
               "linea": _tab_timeline, "comentarios": _tab_comments}[tab]
    ctx.update(builder(case, snap, items))
    return render_template("claims/case.html", **ctx)


def _overview(case, c, snap, items) -> dict:
    """Lo que muestran la ficha del expediente y la vista previa de la cola: veredicto y alertas agrupadas."""
    findings = sorted((snap or {}).get("findings", []), key=lambda f: SEV_ORDER[f["severity"]])
    thumbs = {i["digest"][:8]: i for i in items if i["is_image"]}
    groups = _group_findings(findings, thumbs, {i["digest"][:8]: i for i in items})
    return {"groups": groups, "verdict": _verdict(c, findings, groups)}


def preview_context(case) -> dict:
    """Vista previa de un caso en la cola de trabajo (sin reanalizar ni registrar decisiones)."""
    c = summarize(case)
    snap = service.snapshot(case) or {"findings": []}
    items = evidence_items(case, snap)
    photos = [i for i in items if i["is_image"] and not i["excluded"]]
    return {"p": c, "p_photos": photos[:6], "p_more": max(0, len(photos) - 6), **{"p_" + k: v for k, v in
            _overview(case, c, snap, items).items()}}


@bp.get("/caso/<cid>/vista")
def case_preview(cid):
    case = load_claim(cid)
    ctx = preview_context(case)
    log_access("vista_previa", ctx["p"]["numero"])
    return render_template("claims/_preview.html", **ctx)


def _tab_summary(case, snap, items):
    decl = service.declaration(case) or {}
    return {"decl": decl, "todo": _todo(case, items), "team": analysts() if has_perm("equipo") else [],
            "can_reassign": has_perm("equipo"), **_ia(case)}


def _group_findings(findings, thumbs, allitems=None) -> list[dict]:
    """Alertas de la misma regla juntas («3 fotos sin metadatos» en una sola línea), de la más grave a la más leve."""
    from evidex.claims.report import RULE_NAMES
    by_rule: dict[str, dict] = {}
    for f in findings:                                    # ya vienen ordenadas por gravedad
        g = by_rule.setdefault(f["rule"], {"rule": f["rule"], "severity": f["severity"], "findings": [], "refs": []})
        if SEV_ORDER[f["severity"]] < SEV_ORDER[g["severity"]]:
            g["severity"] = f["severity"]
        ref = next((thumbs[e] for e in f["evidence"] if e in thumbs), None)
        base, _, rest = f["title"].partition(" (")
        label = rest[:-1] if rest.endswith(")") else (ref["title"] if ref else "")
        pair = [(allitems or thumbs)[e]["digest"] for e in f["evidence"] if e in (allitems or thumbs)][:2] \
            if f["rule"] in PAIR_RULES else []
        if f["rule"] == "photo_differs_from_video" and allitems:          # la foto primero, el video después
            kinds = {i["digest"]: i["kind"] for i in allitems.values()}
            pair.sort(key=lambda d: kinds.get(d) == "video")
        g["findings"].append({**f, "ref": ref, "base": base, "label": label, "pair": pair if len(pair) == 2 else None})
        if ref and ref not in g["refs"]:
            g["refs"].append(ref)
    out = []
    for g in by_rule.values():
        n = len(g["findings"])
        g["count"] = n
        bases = {f["base"] for f in g["findings"]}
        g["title"] = (g["findings"][0]["title"] if n == 1 else
                      bases.pop() if len(bases) == 1 else RULE_NAMES.get(g["rule"], g["findings"][0]["base"]))
        out.append(g)
    return sorted(out, key=lambda g: (SEV_ORDER[g["severity"]], -g["count"]))


def _verdict(c, findings, groups) -> dict:
    """La conclusión del caso en una frase, para la franja de arriba del Resumen."""
    n = {s: sum(1 for f in findings if f["severity"] == s) for s in ("alta", "media", "baja")}
    head = {"bad": "Riesgo alto: hay señales fuertes que justifican investigar.",
            "warn": "Riesgo medio: el liquidador debe revisar las alertas antes de decidir.",
            "ok": "Riesgo bajo: Evidex no encontró señales relevantes.",
            "none": "Aún no se analiza este caso."}.get(c["level"], "")
    if findings:
        partes = [f"{v} {k}{'s' if v != 1 else ''}" for k, v in n.items() if v]
        detail = (f"{len(findings)} alerta{'s' if len(findings) != 1 else ''} de {len(groups)} "
                  f"tipo{'s' if len(groups) != 1 else ''} ({', '.join(partes)}).")
    else:
        detail = "Sin alertas." if c["level"] != "none" else ""
    keep = {"Word", "PDF", "RUT", "IA", "WhatsApp", "Galaxy", "Google", "Samsung", "iPhone"}
    titles = [t[0].lower() + t[1:] if t[1:2].islower() and t.split(" ")[0] not in keep else t
              for t in (g["title"].split(" (")[0] for g in groups[:3])]
    why = ""
    if titles:
        lista = titles[0] if len(titles) == 1 else ", ".join(titles[:-1]) + " y " + titles[-1]
        why = f"Principales señales: {lista}."
    return {"head": head, "detail": detail, "counts": n, "why": why}


def _ia(case) -> dict:
    from evidex.claims import ia_texto
    return {"ia": ia_texto.cargar(case), "ia_on": ia_texto.activa(load_settings()), "ia_key": bool(ia_texto.clave()),
            "ia_tareas": ia_texto.TAREAS}


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


def _tab_timeline(case, snap, items):
    """Todo lo que pasó, en orden: antes del siniestro, el siniestro y después. Lo anterior al choque se marca."""
    from datetime import datetime
    t0 = snap.get("t0") or (service.declaration(case) or {}).get("fecha_siniestro")
    thumbs = {i["digest"][:8]: i for i in items if i["is_image"]}
    days, cur = [], None
    for e in snap.get("timeline") or []:
        try:
            ts = datetime.fromisoformat(e["ts"][:16])
        except (TypeError, ValueError):
            continue
        phase = ("antes" if t0 and e["ts"][:16] < t0[:16] and e["kind"] != "siniestro" else
                 "siniestro" if e["kind"] == "siniestro" else "despues")
        if e["kind"] == "poliza":
            phase = "contexto"
        day = ts.strftime("%d-%m-%Y")
        if not cur or cur["day"] != day:
            cur = {"day": day, "events": []}
            days.append(cur)
        cur["events"].append({**e, "time": ts.strftime("%H:%M"), "phase": phase, "thumb": thumbs.get(e.get("ev") or "")})
    n_before = sum(1 for d in days for e in d["events"] if e["phase"] == "antes")
    return {"days": days, "n_before": n_before, "t0": t0, "has_timeline": "timeline" in snap}


def _tab_photos(case, snap, items):
    from evidex.forensics import video
    from evidex.forensics.training_bank import APPS, ORIGENES
    info = {v["digest"]: v for v in snap.get("videos", [])}
    vids = [{**i, "video": info.get(i["digest"])} for i in items if i["kind"] == "video"]
    return {"items": [i for i in items if i["kind"] == "foto"], "videos": vids, "video_on": video.available(),
            "teach_apps": APPS, "teach_origins": ORIGENES}


def _tab_docs(case, snap, items):
    return {"items": [i for i in items if i["kind"] not in ("foto", "video")], **_ia(case)}


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
                                                                         "derivation_delivered")], **_ia(case)}


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
               cap_local=tunnel.is_local(cap_url), cap_temp=tunnel.is_temporary(cap_url),
               cap_moved=links.address_changed(cap, public_base()))
    return out


def _tab_comments(case, snap, items):
    u = current_user()
    if u:
        comments.mark_read(cx.workdir, case.root.name, u["username"])
    people = comments.mentionable(cx.store, case, exclude=u["username"] if u else "") if cx.store.enabled() else []
    return {"comments": comments.listing(case)[::-1], "people": people, "max_len": comments.MAX_LEN}


@bp.post("/caso/<cid>/comentar")
def comment_add(cid):
    """Comentario interno: queda en la cadena de custodia; avisa en Inicio a quienes se menciona con @usuario."""
    case = load_claim(cid)
    u = current_user()
    if not u:
        abort(403)
    try:
        entry, ignored = comments.add(cx.workdir, case, cx.store, u["username"], u["name"], request.form.get("texto", ""))
    except ValueError as ex:
        flash(str(ex), "bad")
        return redirect(url_for("claims.case_view", cid=cid, tab="comentarios"))
    log_access("comentario", summarize(case)["numero"])
    if ignored:
        flash("No se avisó a " + ", ".join("@" + n for n in ignored) + ": no existe o no puede ver este caso.", "warn")
    return redirect(url_for("claims.case_view", cid=cid, tab="comentarios") + f"#c-{entry['seq']}")


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
                  "evidence_purged": f"{d.get('original_name', '')} · motivo: {d.get('reason', '')}",
                  "llm_used": f"{d.get('tarea', '')} · {d.get('servicio', '')} ({d.get('modelo', '')})",
                  "training_marked": f"{d.get('original_name', '')}: {'editada con IA' if d.get('label') == 'editada' else 'sin editar'}"
                                     + (f" ({d['app']})" if d.get("app") else ""),
                  "claim_analyzed": f"{d.get('findings', 0)} hallazgo(s), riesgo {d.get('score', '—')}",
                  "comentario": " ".join(d.get("texto", "").split())[:90] + ("…" if len(d.get("texto", "")) > 90 else ""),
                  "cliente_asignado": e["subject"]}.get(e["action"], "")
        rows.append({"ts": e["ts"], "actor": e["actor"], "what": what, "detail": detail, "hash": e["hash"]})
    return {"rows": rows[::-1], "accesos": cx.store.entries(subject=summarize(case)["numero"], limit=50) if cx.store.enabled() else []}


# ---- acciones del caso ----------------------------------------------------------------------------
@bp.get("/caso/<cid>/informe")
def report(cid):
    case = load_claim(cid)
    return send_file(case.root / "informe.html", mimetype="text/html")


@bp.get("/caso/<cid>/analisis")
def analysis_status(cid):
    """Para que la página del caso sepa cuándo terminó el análisis en segundo plano."""
    from evidex.web import background
    case = load_claim(cid)
    st = background.status(case)
    return {"running": background.is_running(case), "state": st.get("state"), "finished": st.get("finished")}


@bp.post("/caso/<cid>/analizar")
def reanalyze(cid):
    r = run_claim_analysis(load_claim(cid))
    if r is None or r.get("background"):
        if r:
            flash("Analizando el caso. Puede seguir trabajando: la página se actualiza sola al terminar.", "info")
        return redirect(url_for("claims.case_view", cid=cid, tab=request.form.get("tab") or None))
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
