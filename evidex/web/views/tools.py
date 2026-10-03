"""Herramientas sueltas: revisar una foto."""
from __future__ import annotations

import tempfile
from pathlib import Path

from flask import Blueprint, render_template, request
from werkzeug.utils import secure_filename


bp = Blueprint("tools", __name__)


@bp.route("/foto", methods=["GET", "POST"])
def photo_check():
    from evidex.claims.analysis import quick_check
    results = []
    if request.method == "POST":
        fecha = (request.form.get("fecha") or "").strip() or None
        if fecha and len(fecha) == 16:
            fecha += ":00"
        for up in request.files.getlist("fotos"):
            if not up or not up.filename:
                continue
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / (secure_filename(up.filename) or "foto")
                up.save(path)
                meta, findings = quick_check(path, up.filename, fecha)
                from evidex.forensics.image_content import overlay
                import base64
                ov = overlay(path, meta.get("content") or {})
                marked = base64.b64encode(ov).decode() if ov else None
                ela = noise = None
                if "error" not in meta:
                    from evidex.forensics.image_content import ela_map, noise_map
                    try:
                        ela = base64.b64encode(ela_map(path)).decode()
                        noise = base64.b64encode(noise_map(path)).decode()
                    except Exception:
                        pass
            level = "bad" if any(f.severity == "alta" for f in findings) else \
                "warn" if any(f.severity == "media" for f in findings) else "ok"
            fx = meta.get("forensics") or {}
            dates = fx.get("dates") or {}
            rows = [("Formato y tamaño", f"{meta.get('format')} {meta.get('width')}×{meta.get('height')}"),
                    ("Cámara", " ".join(filter(None, [meta.get("make"), meta.get("model")])) or "—"),
                    ("Software", meta.get("software") or "—")]
            rows += [(f"Fecha {k}", v.replace("T", " ")) for k, v in dates.items()] or [("Fecha", "—")]
            rows += [("Zona horaria", fx.get("offset") or "—"),
                     ("Hora GPS (UTC)", (fx.get("gps_utc") or "—").replace("T", " ")),
                     ("Ubicación GPS", ", ".join(f"{x:.5f}" for x in meta["gps"]) if meta.get("gps") else "—"),
                     ("Datos de exposición", "sí" if fx.get("exposure") else "no"),
                     ("Miniatura interna", "sí" if fx.get("thumb_dhash") else "no"),
                     ("Herramientas detectadas", ", ".join(fx.get("tools") or []) or "—")]
            ct = meta.get("content") or {}
            gh = ct.get("ghost") or {}
            rows += [("Calidad JPEG estimada", gh.get("q_final") or "—"),
                     ("Compresión anterior", f"sí, calidad ~{gh['q_first']}" if gh.get("q_first") else "no detectada"),
                     ("Zonas clonadas", "sí" if (ct.get("clone") or {}).get("src") else "no detectadas"),
                     ("Grano del sensor", "zona distinta" if (ct.get("noise") or {}).get("region") else "parejo"),
                     ("Tamaño anotado por la cámara", "×".join(map(str, fx["pixel_dims"])) if fx.get("pixel_dims") else "—"),
                     ("Identificador único de la foto", fx.get("image_uid") or "—"),
                     ("N° de serie de la cámara", fx.get("serial") or "—")]
            rows.append(("Texto leído en la imagen", (ct.get("ocr") or {}).get("text") or "—"))
            cp = ct.get("c2pa")
            rows.append(("Firma de autenticidad (C2PA)", "no tiene" if not cp else
                         cp.get("note") or ("válida" if cp.get("valid") else f"inválida ({cp.get('state')})")
                         + (f" · {cp['generator']}" if cp.get("generator") else "")))
            if "error" in meta:
                rows = [("Error", meta["error"])]
            from evidex.claims import photo_checks
            checks = photo_checks.run(meta, findings, case_level=False)
            if not fecha:
                for ck in checks:
                    if ck["name"].startswith("Fecha de la foto contra") and ck["status"] == "ok":
                        ck.update(status="no aplica", why="no se indicó la fecha del siniestro")
            results.append({"name": up.filename, "findings": findings, "level": level, "rows": rows, "marked": marked,
                            "ela": ela, "noise": noise, "checks": checks})
    return render_template("tools/photo_check.html", results=results, active="foto")
