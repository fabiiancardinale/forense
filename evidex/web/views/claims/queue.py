"""Cola de trabajo, registro de siniestros y carga del ejemplo."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from flask import flash, g, redirect, render_template, request, url_for

from evidex.claims import assignment, service
from evidex.portal.links import DEFAULT_DOCS, DOC_TYPES
from evidex.web.common import (FORM_FIELDS, actor_name, analysts, claim_list, current_user, cx, has_perm, level_counts,
                                save_uploads, sees_all_claims)
from evidex.web.views.claims import bp


@bp.get("/siniestros")
def index():
    """Cola de trabajo. El analista ve sus casos; el jefe puede filtrar por analista."""
    everyone = sees_all_claims()
    cases = claim_list(everyone=everyone)
    who = request.args.get("analista", "")
    if everyone and who:
        cases = [c for c in cases if (c["owner"] or "") == ("" if who == "-" else who)]
    return render_template("claims/queue.html", cases=cases, counts=level_counts(cases), workdir=cx.workdir,
                           active="index", everyone=everyone, who=who, team=analysts() if everyone else [])


def _new_form(f, error=None, status=200):
    return render_template("claims/new.html", f=f, error=error, active="new", doc_types=DOC_TYPES,
                           default_docs=DEFAULT_DOCS, team=analysts(), assign_choice=has_perm("equipo")), status


@bp.route("/nuevo", methods=["GET", "POST"])
def new_claim():
    f = request.form
    if request.method == "GET":
        return _new_form({})

    def fail(msg):
        return _new_form(f, msg, 400)

    numero = f.get("numero", "").strip()
    fecha = f.get("fecha_siniestro", "").strip()
    if not numero or not fecha:
        return fail("El número de siniestro y la fecha son obligatorios.")
    cid = service.case_id(numero)
    if not cid:
        return fail("El número de siniestro debe contener letras o números.")
    if (cx.workdir / cid / "case.json").exists():
        return fail(f"Ya existe un siniestro con el número {numero}.")
    decl = {k: f.get(k, "").strip() for k in FORM_FIELDS}
    decl["fecha_siniestro"] = fecha if len(fecha) > 16 else fecha + ":00"
    lat, lon = f.get("lat", "").strip(), f.get("lon", "").strip()
    if lat or lon:
        try:
            decl["lat"], decl["lon"] = float(lat.replace(",", ".")), float(lon.replace(",", "."))
        except ValueError:
            return fail("Latitud y longitud deben ser números, por ejemplo -33.4263 y -70.6167.")
    decl = {k: v for k, v in decl.items() if v != ""}
    owner = _owner_from_form(f)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        photos, rejected = save_uploads(request.files.getlist("fotos"), td)
        if rejected:
            return fail("Estos archivos no se aceptaron: " + ", ".join(rejected))
        send_link = f.get("enviar_enlace") == "1"
        if not photos and not send_link:
            return fail("Agregue al menos una foto o documento del siniestro, o marque la opción de enviar el enlace al asegurado.")
        dpath = td / "declaracion.json"
        dpath.write_text(json.dumps(decl, indent=2, ensure_ascii=False), encoding="utf-8")
        case = service.create_claim(cx.workdir, cid, dpath, photos)
    if owner:
        assignment.assign(case, owner[0], owner[1], actor_name() or owner[1], "registro del caso")
    if send_link:
        from evidex.portal import links
        links.create_link(case, actor=actor_name() or "analista", docs=f.getlist("docs"),
                          custom=f.get("docs_custom", "").split(";"))
    r = service.analyze_claim(case, cx.registry)
    if send_link:
        flash("Siniestro registrado. Envíe ahora el enlace al asegurado desde la pestaña Asegurado.", "ok")
    else:
        flash(f"Siniestro creado y analizado: {r['photos']} foto(s), {r['documents']} documento(s), "
              f"{r['findings']} hallazgo(s).", "ok")
    if r.get("reanalyzed"):
        flash("Se reanalizaron los siniestros vinculados: " + ", ".join(r["reanalyzed"]) + ".", "info")
    return redirect(url_for("claims.case_view", cid=cid, tab="asegurado" if send_link else None))


def _owner_from_form(f) -> tuple[str, str] | None:
    """Analista responsable: el propio analista; el jefe puede elegir; en modo demo se escribe el nombre."""
    u = current_user()
    if u and u["role"] == "analista":
        return u["username"], u["name"]
    chosen = f.get("analista", "").strip()
    if chosen and cx.store.enabled():
        match = next((a for a in analysts() if a["username"] == chosen), None)
        if match:
            return match["username"], match["name"]
    if chosen and not cx.store.enabled():
        return chosen.lower().replace(" ", "."), chosen
    return (u["username"], u["name"]) if u else None


@bp.post("/demo")
def load_demo():
    if not service.DEMO_SCRIPT.exists():
        flash("No se encontró el generador de ejemplo (demo/make_claim_demo.py).", "bad")
        return redirect(url_for("claims.index"))
    done = service.load_demo(cx.workdir)
    u = g.get("user")
    me = (u["username"], u["name"]) if u and u["role"] == "analista" else None
    assignment.seed_demo_team(cx.workdir, [n for n, _ in done], actor_name() or "ejemplo", me)
    if done:
        flash(f"Ejemplo cargado: {len(done)} siniestros ficticios, con fotos y documentos sintéticos, repartidos entre "
              "analistas de ejemplo. Abra SIN-2026-0987 para ver la red de siniestros vinculados.", "info")
    else:
        flash("El ejemplo ya estaba cargado.", "info")
    return redirect(url_for("claims.index"))
