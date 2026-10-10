"""Enseñarle al modelo: marcar fotos de un caso como «editada con IA» o «sin editar» y exportar el banco para
entrenar en Kaggle. El modelo nunca se reentrena ni se instala solo (ver evidex/forensics/training_bank.py)."""
from __future__ import annotations

import io
from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for

from evidex.claims import service
from evidex.forensics import training_bank as TB
from evidex.web.common import actor_name, cx, has_perm, load_claim, log_access

bp = Blueprint("training", __name__)


def bank() -> TB.Bank:
    return TB.Bank(cx.workdir)


def _model_result(case, digest: str) -> dict:
    from evidex.web.views.claims.evidence import _content
    return _content(case, digest).get("learned") or {}


@bp.post("/caso/<cid>/archivo/<digest>/entrenar")
def mark(cid, digest):
    case = load_claim(cid)
    back = redirect(url_for("claims.case_view", cid=cid, tab="fotos") + f"#f-{digest[:12]}")
    if not TB.DIGEST.fullmatch(digest or "") or not service.has_evidence(case, digest) or digest in case.purged():
        abort(404)
    f = request.form
    if f.get("confirmo") != "si":
        flash("Para enseñarle al modelo confirme que la foto se puede usar para entrenar.", "bad")
        return back
    from evidex.web.views.claims.evidence import _evidence_name
    original = f.get("original", "")
    orig_path = None
    if original:
        if not TB.DIGEST.fullmatch(original) or not service.has_evidence(case, original) or original in case.purged():
            flash("La foto original indicada no es de este caso.", "bad")
            return back
        orig_path = case.evidence_dir / original
    name = _evidence_name(case, digest)
    try:
        row = bank().mark(case.evidence_dir / digest, digest, etiqueta=f.get("etiqueta", ""), origen=f.get("origen", ""),
                          actor=actor_name() or "analista", caso=(service.declaration(case) or {}).get("numero") or cid,
                          nombre=name, app=f.get("app", ""), alcance=f.get("alcance", "zona"), original=orig_path,
                          original_digest=original, modelo=_model_result(case, digest), nota=f.get("nota", ""))
    except ValueError as ex:
        flash(str(ex), "bad")
        return back
    case.ledger.append(actor_name() or "analista", "training_marked", digest,
                       {"original_name": name, "label": row["etiqueta"], "origin": row["origen"], "app": row["app"]})
    log_access("ensenar_modelo", f"{name}: {row['etiqueta']}")
    msg = f"«{name}» guardada en el banco de entrenamiento como {'editada' if row['etiqueta'] == 'editada' else 'sin editar'}."
    if row["etiqueta"] == "editada":
        if row["mascara"]:
            msg += f" Zona calculada con la original ({round((row['cobertura'] or 0) * 100, 1)} % de la foto): revísela en el banco."
        elif original:
            msg += " No se encontró una diferencia clara con la original (¿es la misma foto o está recortada?)."
        elif row["alcance"] != "completa":
            msg += " Sin la foto original no se sabe qué zona cambió: agregue la original para que sirva para entrenar."
    if row["modelo_acerto"] is False:
        msg += " El modelo se había equivocado con esta foto."
    flash(msg, "ok")
    return back


@bp.get("/entrenamiento")
def index():
    b = bank()
    return render_template("training/index.html", entries=b.entries(), s=b.summary(), etiquetas=TB.ETIQUETAS,
                           origenes=TB.ORIGENES, alcances=TB.ALCANCES, can_export=has_perm("admin"), active="entrenar")


@bp.get("/entrenamiento/<digest>.jpg")
def preview(digest):
    b = bank()
    p = b.photo(digest)
    if p is None:
        abort(404)
    return send_file(io.BytesIO(TB.overlay(p, b.mask(digest))), mimetype="image/jpeg", max_age=0)


@bp.post("/entrenamiento/<digest>/quitar")
def remove(digest):
    e = bank().get(digest)
    if not e or not bank().remove(digest, actor_name() or "analista", request.form.get("motivo", "")):
        abort(404)
    log_access("ensenar_modelo", f"quitó {e.get('nombre', digest[:12])} del banco")
    flash(f"«{e.get('nombre', digest[:12])}» quitada del banco de entrenamiento (su copia se borró; el caso no cambia).", "ok")
    return redirect(url_for("training.index"))


def _original_path(e: dict):
    """La foto original de una editada: en el banco si también se marcó, si no en su caso."""
    d = e.get("original") or ""
    if not TB.DIGEST.fullmatch(d):
        return None
    p = bank().photo(d)
    if p is not None:
        return p
    case = service.find_case(cx.workdir, e.get("caso") or "")
    if case is not None and service.has_evidence(case, d) and d not in case.purged() and (case.evidence_dir / d).exists():
        return case.evidence_dir / d
    return None


@bp.post("/entrenamiento/recalcular")
def remask_all():
    """Vuelve a calcular la zona de todas las editadas que tienen su original."""
    b, n, sin = bank(), 0, 0
    for e in b.entries():
        if e["etiqueta"] == "editada" and e.get("original"):
            o = _original_path(e)
            if o is None:
                sin += 1
            elif b.remask(e["digest"], o, actor_name() or "analista"):
                n += 1
    log_access("ensenar_modelo", f"recalculó {n} zonas")
    flash(f"Zonas recalculadas: {n}." + (f" {sin} sin su original disponible." if sin else ""), "ok")
    return redirect(url_for("training.index"))


@bp.get("/entrenamiento/exportar")
def export():
    b = bank()
    if not b.entries():
        flash("El banco está vacío.", "info")
        return redirect(url_for("training.index"))
    log_access("exporta_entrenamiento", f"{b.summary()['total']} fotos")
    return send_file(io.BytesIO(b.export_zip()), mimetype="application/zip", as_attachment=True,
                     download_name=f"evidex_banco_entrenamiento_{datetime.now():%Y%m%d}.zip")
