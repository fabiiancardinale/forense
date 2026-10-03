"""Informe HTML autocontenido: resumen verificado, hallazgos, línea de tiempo y custodia."""
from __future__ import annotations

import html
import re

from evidex.core.assistant import CITE
from evidex.claims.guide import for_rule
from evidex.core.compliance import deadlines
from evidex.core.ledger import verify_chain, verify_seal

CSS = """
:root{--ink:#0f1b2d;--muted:#667588;--line:#e3e8ef;--bg:#f3f5f8;--card:#fff;--accent:#14508c;
--red:#b42318;--redbg:#fef3f2;--amb:#b54708;--ambbg:#fffaeb;--grn:#067647;--grnbg:#ecfdf3}
*{box-sizing:border-box}body{margin:0;font:14.5px/1.55 Inter,system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);background:var(--bg)}
header{background:#0b1f36;color:#fff;padding:28px 0 24px}
.wrap{max-width:1000px;margin:0 auto;padding:0 20px}
.brand{font-size:12px;letter-spacing:.18em;text-transform:uppercase;opacity:.7}
header h1{margin:6px 0 4px;font-size:26px}header p{margin:0;opacity:.75}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:-18px 0 8px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.tile b{display:block;font-size:24px}.tile span{color:var(--muted);font-size:12.5px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 22px;margin:16px 0}
h2{font-size:16px;margin:0 0 12px}
.checks{display:flex;flex-wrap:wrap;gap:8px}.chk{padding:6px 12px;border-radius:99px;font-weight:600;font-size:13px}
.ok{background:var(--grnbg);color:var(--grn)}.bad{background:var(--redbg);color:var(--red)}
.claims{margin:0;padding-left:18px}.claims li{margin:6px 0}
.cite{display:inline-block;font:11.5px ui-monospace,monospace;background:#eef3f9;color:var(--accent);
border-radius:4px;padding:0 5px;margin-left:2px;text-decoration:none}
.note{color:var(--muted);font-size:13px;margin:10px 0 0}
.finding{border-left:4px solid var(--line);padding:6px 0 6px 14px;margin:10px 0}
.finding.alta{border-color:var(--red)}.finding.media{border-color:var(--amb)}
.sev{font-size:11px;font-weight:700;padding:2px 7px;border-radius:4px;margin-right:6px}
.sev.alta{background:var(--redbg);color:var(--red)}.sev.media{background:var(--ambbg);color:var(--amb)}
.finding p{margin:4px 0;color:var(--muted)}
.finding.withpic{display:grid;grid-template-columns:132px 1fr;gap:14px;align-items:start}
.fthumb{display:block;text-decoration:none;color:var(--muted)}
.fthumb img{width:132px;height:100px;object-fit:cover;border-radius:8px;border:1px solid var(--line);display:block;background:#eef1f4}
.fthumb .noimg{display:grid;place-items:center;width:132px;height:100px;border-radius:8px;border:1px dashed var(--line);font-size:11px}
.fthumb small{display:block;font-size:11px;margin-top:4px;line-height:1.3;overflow-wrap:anywhere}
.fthumb:hover img{outline:3px solid #f2c200}
.tips{background:#f7f9fc;border-radius:8px;padding:8px 12px;margin:8px 0 4px}
.tips p{margin:3px 0;font-size:13px;color:var(--ink)}.tips b{color:var(--ink)}
.finding p.evid{font-size:12.5px}
@media (max-width:640px){.finding.withpic{grid-template-columns:1fr}.fthumb img{width:100%;height:160px}}
table{border-collapse:collapse;width:100%;font-size:13px}
th{text-align:left;color:var(--muted);font-weight:600;border-bottom:2px solid var(--line);padding:6px 8px}
td{border-bottom:1px solid var(--line);padding:6px 8px;vertical-align:top}
tr.hit td{background:#fffaf0}tr:target td{background:#fff1a8}
code{font:12px ui-monospace,monospace}
.scroll{overflow-x:auto}
footer{color:var(--muted);font-size:12px;text-align:center;padding:20px 0 40px}
"""


def _link_cites(text: str, label=lambda i: i.split(":")[1]) -> str:
    esc = html.escape(text)
    esc = re.sub(r"\s*\[ev:([0-9a-f]{8}:\d+)\]",
                 lambda m: f' <a class="cite" href="#ev-{m.group(1)}">{label(m.group(1))}</a>', esc)
    return esc.replace("</a>.", "</a>")


def _integrity(case):
    import json
    entries = case.ledger.entries()
    chain_ok, chain_msg = verify_chain(entries)
    ev_ok, ev_problems = case.verify_evidence()
    seal_path = case.root / "seal.json"
    if seal_path.exists():
        ok, _ = verify_seal(entries, json.loads(seal_path.read_text(encoding="utf-8")), case.ledger.pub_path.read_bytes())
        seal_txt = ("Firma digital válida" if ok else "Firma inválida"), ok
    else:
        seal_txt = ("Sin firma", False)
    return entries, chain_ok, chain_msg, ev_ok, ev_problems, seal_txt


def _integrity_html(chain_ok, chain_msg, ev_ok, ev_problems, seal_txt) -> str:
    return (f'<section><h2>Integridad de la evidencia</h2><div class="checks">'
            f'<span class="chk {"ok" if chain_ok else "bad"}">Cadena de custodia: {html.escape(chain_msg)}</span>'
            f'<span class="chk {"ok" if ev_ok else "bad"}">'
            f'{"Hashes de evidencia coinciden" if ev_ok else html.escape("; ".join(ev_problems))}</span>'
            f'<span class="chk {"ok" if seal_txt[1] else "bad"}">{seal_txt[0]} (Ed25519)</span></div>'
            f'<p class="note">Cualquier tercero puede comprobar esto con <code>verify.py</code>, '
            f"incluido en el paquete exportado.</p></section>")


ACTIONS = {"case_created": "Caso creado", "evidence_added": "Archivo agregado", "analysis_run": "Análisis",
           "claim_analyzed": "Análisis de Evidex", "evidence_excluded": "Archivo quitado del análisis",
           "evidence_restored": "Archivo restaurado", "case_assigned": "Caso asignado", "case_derived": "Derivado a peritaje",
           "derivation_cancelled": "Derivación anulada", "derivation_delivered": "Perito entregó informe final",
           "decision": "Decisión", "capture_link_created": "Enlace al asegurado creado",
           "portal_finished": "Asegurado terminó de subir", "imported_from": "Importado del historial",
           "timeline_built": "Línea de tiempo", "alert_response": "Respuesta a alerta", "conclusion": "Conclusión",
           "dossier_delivered": "Informe final entregado", "audit_run": "Auditoría"}


def _action_text(e) -> str:
    txt = html.escape(ACTIONS.get(e["action"], e["action"]))
    d = e.get("data") or {}
    if e["action"] == "evidence_added" and d.get("original_name"):
        txt += f' <small>{html.escape((d.get("portal") or {}).get("title") or d["original_name"])}</small>'
    elif e["action"] == "evidence_excluded" and d.get("reason"):
        txt += f' <small>({e["subject"][:8]}) motivo: {html.escape(d["reason"])}</small>'
    elif e["action"] == "evidence_restored":
        txt += f' <small>({e["subject"][:8]})</small>'
    return txt


def _custody_html(entries) -> str:
    h = ['<section><h2>Cadena de custodia</h2><div class="scroll"><table><tr><th>#</th><th>Hora (UTC)</th>'
         "<th>Quién</th><th>Acción</th><th>Hash</th></tr>"]
    for e in entries:
        h.append(f'<tr><td>{e["seq"]}</td><td>{e["ts"].replace("T", " ").rstrip("Z")}</td><td>{html.escape(e["actor"])}</td>'
                 f'<td>{_action_text(e)}</td><td><code>{e["hash"][:16]}…</code></td></tr>')
    h.append("</table></div></section>")
    return "".join(h)


def build(case, timeline, findings, verified, ovi=False) -> str:
    entries, chain_ok, chain_msg, ev_ok, ev_problems, seal_txt = _integrity(case)

    rows = timeline.all()
    hit_ids = {i for f in findings for i in f.evidence}
    high = sum(1 for f in findings if f.severity == "alta")
    hosts = len({r["host"] for r in rows if r["host"]})
    detected = findings[0].first_ts if findings else (rows[0]["ts"] if rows else "")
    all_ok = chain_ok and ev_ok and seal_txt[1]

    h = [f"<!doctype html><html lang=es><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
         f"<title>Informe {html.escape(case.name)}</title><style>{CSS}</style>"]
    h.append(f'<header><div class="wrap"><div class="brand">Evidex · Informe de incidente</div>'
             f"<h1>{html.escape(case.name)}</h1><p>Detectado {detected.replace('T', ' ').replace('Z', ' UTC')}</p></div></header>")
    h.append('<div class="wrap"><div class="tiles">')
    for val, lbl in [(len(rows), "eventos analizados"), (hosts, "equipos"), (len(findings), "hallazgos"),
                     (high, "de severidad alta"), ("✓" if all_ok else "✗", "evidencia íntegra")]:
        h.append(f'<div class="tile"><b>{val}</b><span>{lbl}</span></div>')
    h.append("</div>")

    h.append(_integrity_html(chain_ok, chain_msg, ev_ok, ev_problems, seal_txt))

    h.append("<section><h2>Resumen</h2><ul class=claims>")
    for s in verified.accepted:
        h.append(f"<li>{_link_cites(s)}</li>")
    h.append("</ul>")
    h.append(f'<p class="note">Cada afirmación enlaza al evento que la respalda. '
             f'{len(verified.rejected)} afirmación(es) sin evidencia fueron descartadas automáticamente.</p></section>')

    h.append("<section><h2>Hallazgos</h2>")
    for f in findings:
        cites = "".join(f'<a class="cite" href="#ev-{i}">{i.split(":")[1]}</a>' for i in f.evidence)
        h.append(f'<div class="finding {f.severity}"><span class="sev {f.severity}">{f.severity.upper()}</span>'
                 f"<b>{html.escape(f.title)}</b><p>{html.escape(f.summary)}</p>"
                 f'<p>{f.first_ts.replace("T", " ").replace("Z", "")} · evidencia {cites}</p></div>')
    h.append("</section>")

    if detected:
        h.append("<section><h2>Plazos de reporte (Ley 21.663)</h2><table><tr><th>Obligación</th><th>Fecha límite</th></tr>")
        for name, when in deadlines(detected, ovi):
            h.append(f"<tr><td>{html.escape(name)}</td><td><b>{when}</b></td></tr>")
        h.append(f'</table><p class="note">Contado desde la primera señal del incidente. Confirmar con la ANCI y asesoría legal.</p></section>')

    h.append('<section><h2>Línea de tiempo</h2><div class="scroll"><table><tr><th>#</th><th>Hora (UTC)</th><th>Equipo</th>'
             "<th>Evento</th><th>Usuario</th><th>Detalle</th></tr>")
    for r in rows:
        cls = ' class="hit"' if r["id"] in hit_ids else ""
        h.append(f'<tr id="ev-{r["id"]}"{cls}><td><code>{r["id"].split(":")[1]}</code></td>'
                 f'<td>{r["ts"][11:19]}</td><td>{html.escape(r["host"] or "")}</td>'
                 f'<td>{r["event_id"] or ""}</td><td>{html.escape(r["user"] or "")}</td>'
                 f'<td>{html.escape((r["message"] or "")[:110])}</td></tr>')
    h.append("</table></div></section>")

    h.append(_custody_html(entries))
    h.append("<footer>Generado por Evidex by Zelekpress · prototipo</footer></div></html>")
    return "\n".join(h)




# ---- informe de siniestro (para el liquidador) ---------------------------------
CLAIM_CSS = """
.rec{display:flex;align-items:center;gap:18px;border-radius:10px;padding:16px 20px;margin:16px 0;font-weight:600;font-size:16px}
.rec.bad{background:var(--redbg);color:var(--red);border:1px solid #f3c5c1}
.rec.warn{background:var(--ambbg);color:var(--amb);border:1px solid #f1d9ad}
.rec.ok{background:var(--grnbg);color:var(--grn);border:1px solid #bfe3cb}
.rec.none{background:#f2f4f7;color:#475467;border:1px solid var(--line)}
.rec small{display:block;font-weight:400;color:var(--muted);font-size:13px}
.score{flex:none;width:74px;height:74px;border-radius:50%;display:grid;place-items:center;background:#fff;
border:5px solid currentColor;font-size:22px;font-weight:800;line-height:1}
.score span{display:block;font-size:10px;font-weight:600;color:var(--muted);text-align:center}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:8px 28px}
.cols h3{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:8px 0 6px}
dl.decl{display:grid;grid-template-columns:max-content 1fr;gap:3px 14px;margin:0;font-size:13.5px}
dl.decl dt{color:var(--muted)}dl.decl dd{margin:0;overflow-wrap:anywhere}
.relato{background:var(--bg);border-left:3px solid var(--line);padding:10px 14px;margin:12px 0 0;border-radius:0 8px 8px 0}
.cat{display:flex;align-items:center;gap:8px;margin:18px 0 4px;font-size:13px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}
.cat:first-of-type{margin-top:4px}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:14px}
.photo{border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--card)}
.photo:target,tr:target td,#decl:target{outline:3px solid #f2c200}
.photo img{width:100%;height:160px;object-fit:cover;display:block;background:#ddd}
.photo .body{padding:10px 12px;font-size:12.5px}.photo .body b{font-size:13.5px}
.photo .meta{color:var(--muted);margin:4px 0 6px}
.tag{display:inline-block;font-size:11px;font-weight:700;border-radius:4px;padding:1px 6px;margin:2px 3px 0 0}
.tag.alta{background:var(--redbg);color:var(--red)}.tag.media{background:var(--ambbg);color:var(--amb)}
.tag.baja{background:#eef1f4;color:var(--muted)}.tag.ok{background:var(--grnbg);color:var(--grn)}
svg.net{width:100%;height:auto;max-height:380px;display:block;margin:4px 0 12px}
svg.net .edge{stroke:#9aa7b5;stroke-width:2}svg.net .edge.direct{stroke:var(--red);stroke-width:2.5}
svg.net .elabel{font:11px system-ui,sans-serif;fill:#44505d}
svg.net .nlabel{font:600 12.5px system-ui,sans-serif;fill:var(--ink)}svg.net .nsub{font:11px system-ui,sans-serif;fill:var(--muted)}
svg.net .n-bad{fill:var(--red)}svg.net .n-warn{fill:#c77d00}svg.net .n-ok{fill:var(--grn)}svg.net .n-none{fill:#8a96a3}
svg.net .n-center{fill:var(--accent)}svg.net .halo{fill:#fff;stroke:var(--line);stroke-width:1}
.tl{list-style:none;margin:0;padding:0;position:relative}
.tl::before{content:"";position:absolute;left:118px;top:6px;bottom:6px;width:2px;background:var(--line)}
.tl .day{font-size:11.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:16px 0 6px;
position:relative;z-index:1;background:var(--card);width:max-content;padding:2px 10px 2px 0}
.tl .day:first-child{margin-top:0}
.tl li.ev{display:grid;grid-template-columns:100px 18px 1fr;gap:0 10px;align-items:start;padding:5px 0}
.tl .t{text-align:right;font-variant-numeric:tabular-nums;color:var(--muted);font-size:12.5px;padding-top:2px}
.tl .t small{display:block;font-size:10.5px}
.tl .dot{width:12px;height:12px;border-radius:50%;margin:4px 0 0 3px;background:#fff;border:3px solid #8a96a3;position:relative;z-index:1}
.tl .k-siniestro .dot{border-color:var(--red);background:var(--red)}.tl .k-foto .dot,.tl .k-captura .dot{border-color:var(--accent)}
.tl .k-documento .dot,.tl .k-version .dot{border-color:#7a5af8}.tl .k-chat .dot{border-color:var(--grn)}
.tl .k-poliza .dot,.tl .k-denuncia .dot{border-color:#8a96a3}
.tl .bad .dot{border-color:var(--red);background:var(--redbg)}
.tl .what b{font-size:13.5px}.tl .what .kind{font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);margin-right:6px}
.tl .what p{margin:2px 0 0;color:var(--muted);font-size:12.5px}
.tl .flag{display:inline-block;font-size:11px;font-weight:700;color:var(--red);background:var(--redbg);border-radius:4px;padding:0 6px;margin-left:6px}
.tl li:target{background:#fff8d6;border-radius:6px}
.diff{font:12.5px ui-monospace,SFMono-Regular,Consolas,monospace;border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin:8px 0 4px;background:#fbfcfd}
.diff div{white-space:pre-wrap}.diff .rm{color:var(--red);background:var(--redbg)}.diff .ad{color:var(--grn);background:var(--grnbg)}
.vlinks a{font-size:12px;margin-right:6px}
"""

RULE_NAMES = {
    "shared_contact": "Datos compartidos con otro asegurado", "fraud_ring": "Posible red organizada",
    "frequency_rut": "Siniestros repetidos (RUT)", "frequency_patente": "Siniestros repetidos (patente)",
    "early_claim": "Siniestro poco después de contratar", "before_policy": "Siniestro antes de la vigencia",
    "after_policy": "Siniestro después del vencimiento", "near_end": "Cerca del vencimiento",
    "coverage_change": "Aumento de cobertura reciente", "late_report": "Aviso tardío", "report_before": "Denuncia anterior al siniestro",
    "near_limit": "Monto cercano al tope", "night_no_witness": "Madrugada sin testigos",
    "copied_narrative": "Relato copiado", "time_contradiction": "Relato contradice la hora",
    "witness_contradiction": "Contradicción sobre testigos", "police_missing": "Constancia sin parte", "short_narrative": "Relato muy breve",
    "doc_editor": "PDF pasado por editor", "doc_modified": "PDF modificado", "doc_before_claim": "Documento anterior al siniestro",
    "reused_doc": "Documento repetido", "not_pdf": "PDF inválido", "doc_no_metadata": "PDF sin metadatos",
    "edited": "Foto editada", "reused_photo": "Foto repetida", "no_metadata": "Foto sin metadatos", "ai_generated": "Posible imagen IA",
    "taken_before": "Foto anterior al siniestro", "taken_late": "Foto muy posterior", "gps_mismatch": "Ubicación no coincide",
    "unreadable": "Foto ilegible", "pasted_region": "Zona pegada", "cloned_region": "Zona clonada",
    "recompressed": "Foto guardada de nuevo", "noise_inconsistent": "Grano distinto en una zona",
    "resized_after_capture": "Foto recortada o achicada", "makernote_missing": "Metadatos de iPhone incompletos",
    "ai_dimensions": "Tamaño típico de IA", "edit_filename": "Nombre de archivo de edición",
    "saved_before_taken": "Fecha de la foto cambiada", "same_device_other_claim": "Mismo teléfono en otro siniestro",
    "mirrored_in_claim": "Foto espejada", "duplicate_in_claim": "Foto repetida en el caso",
    "multiple_devices": "Fotos de varios teléfonos", "ai_label_visible": "Marca visible de IA",
    "ai_mark_cropped": "Recortada para ocultar la marca de IA", "cropped_in_claim": "Foto recortada de otra del caso",
    "changed_between_versions": "Zona cambiada entre dos versiones",
    "odd_ratio": "Proporción que no es de cámara",
}

CATEGORY_ORDER = ["Red de siniestros", "Línea de tiempo", "Póliza y siniestro", "Documentos", "Fotos", "Comunicaciones",
                  "Relato", "Datos del asegurado"]
LEVEL_TEXT = {"bad": "Derivado a investigación", "warn": "Revisión manual", "ok": "Sin alertas", None: "Sin analizar"}


def _pdf_thumb(path, size=(160, 200)) -> str:
    """Primera página de un PDF como miniatura (para reconocer el documento)."""
    import base64
    import io
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(path))
        try:
            im = pdf[0].render(scale=0.6).to_pil().convert("RGB")
        finally:
            pdf.close()
        im.thumbnail(size)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=70)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


def _thumb(path, size=(420, 320)) -> str:
    import base64
    import io

    from PIL import Image
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail(size)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=72)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


def _fmt_date(s) -> str:
    if not s:
        return ""
    s = str(s)
    try:
        from datetime import datetime
        d = datetime.fromisoformat(s[:19])
        return d.strftime("%d-%m-%Y %H:%M") if len(s) > 10 else d.strftime("%d-%m-%Y")
    except ValueError:
        return s


def _net_svg(net, center_label: str = "este siniestro") -> str:
    """Grafo radial: el siniestro al centro y los siniestros conectados alrededor.
    Los motivos de cada vínculo se detallan en la tabla, para no saturar el dibujo."""
    import math
    members = net["group"]
    if not members:
        return ""
    W, H, cx, cy, rx, ry = 760, 400, 380, 185, 270, 125
    pos = {net["center"]: (cx, cy)}
    for i, n in enumerate(members):
        a = -math.pi / 2 + 2 * math.pi * i / len(members) + (math.pi / len(members) if len(members) % 2 == 0 else 0)
        pos[n] = (cx + rx * math.cos(a), cy + ry * math.sin(a))
    out = [f'<svg class="net" viewBox="0 0 {W} {H}" role="img" aria-label="Red de siniestros vinculados">']
    for a, b, why in net["group_edges"]:
        (x1, y1), (x2, y2) = pos[a], pos[b]
        direct = net["center"] in (a, b) and center_label == "este siniestro"
        out.append(f'<line class="edge{" direct" if direct else ""}" x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}">'
                   f"<title>{html.escape(a)} – {html.escape(b)}: {html.escape(why)}</title></line>")
    for n, (x, y) in pos.items():
        if n == net["center"]:
            lv = net.get("group_info", {}).get(n, {}).get("level") if center_label != "este siniestro" else None
            cls, sub = (f"n-{lv or 'none'}" if lv else "n-center"), (net.get("group_info", {}).get(n, {}).get("asegurado") or center_label)
        else:
            lv = net["group_info"].get(n, {}).get("level")
            cls, sub = f"n-{lv or 'none'}", net["group_info"].get(n, {}).get("asegurado", "")
        below = y >= cy
        ty = y + 34 if below else y - 36
        out.append(f'<circle class="halo" cx="{x:.0f}" cy="{y:.0f}" r="17"/><circle class="{cls}" cx="{x:.0f}" cy="{y:.0f}" r="13"/>')
        out.append(f'<rect x="{x - 78:.0f}" y="{ty - 14:.0f}" width="156" height="32" rx="6" fill="#fff" opacity=".9"/>')
        out.append(f'<text class="nlabel" x="{x:.0f}" y="{ty:.0f}" text-anchor="middle">{html.escape(n)}</text>')
        out.append(f'<text class="nsub" x="{x:.0f}" y="{ty + 14:.0f}" text-anchor="middle">{html.escape(sub[:28])}</text>')
    out.append("</svg>")
    return "".join(out)


KIND_LABEL = {"siniestro": "Siniestro", "denuncia": "Denuncia", "poliza": "Póliza", "foto": "Foto", "captura": "Captura segura",
              "documento": "Documento", "version": "Versión", "chat": "Chat"}
_DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _weekday(dt) -> str:
    return _DAYS[dt.weekday()]


def _version_cell(d) -> str:
    m = d.meta
    pv = m.get("versions") or {}
    readable = [v for v in pv.get("versions", []) if v.get("readable")]
    if len(readable) < 2:
        return str(m.get("revisions", "—"))
    links = " ".join(f'<a href="documento/{d.digest}/version/{v["n"]}" download>v{v["n"]}</a>' for v in readable)
    return f'{len(readable)} <span class="vlinks">· descargar {links}</span>'


def build_claim(case, decl, decl_ev, photos, findings, verified, rec, docs=(), net=None, score=0) -> str:
    from evidex.claims.analysis import km_between

    net = net or {"center": decl["numero"], "neighbors": {}, "group": [], "group_edges": [], "group_info": {}}
    entries, chain_ok, chain_msg, ev_ok, ev_problems, seal_txt = _integrity(case)
    all_ok = chain_ok and ev_ok and seal_txt[1]
    by_ev: dict[str, list] = {}
    for f in findings:
        for i in f.evidence[:1]:
            by_ev.setdefault(i, []).append(f)
    high = sum(1 for f in findings if f.severity == "alta")

    chat_prefix = {pfx: chat.name for pfx, chat, _ in net.get("chats", [])}

    def label(i):
        if i == decl_ev:
            return "declaración"
        pfx, _, line = i.partition(":")
        return f"chat·{line}" if pfx in chat_prefix else pfx

    def cites(ids):
        return "".join(f'<a class="cite" href="#{"decl" if i == decl_ev else "ev-" + i}">{label(i)}</a>' for i in ids)

    h = [f"<!doctype html><html lang=es><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
         f"<title>Siniestro {html.escape(decl['numero'])}</title><style>{CSS}{CLAIM_CSS}</style>"]
    h.append(f'<header><div class="wrap"><div class="brand">Evidex · Análisis forense de siniestro</div>'
             f"<h1>Siniestro {html.escape(decl['numero'])}</h1>"
             f"<p>{html.escape(decl.get('asegurado', ''))} · Patente {html.escape(decl.get('patente', '—'))} · "
             f"{_fmt_date(decl['fecha_siniestro'])} · {html.escape(decl.get('lugar', ''))}</p></div></header>")
    h.append('<div class="wrap"><div class="tiles">')
    for val, lbl in [(len(findings), "hallazgos"), (high, "de severidad alta"), (len(net["neighbors"]), "siniestros vinculados"),
                     (len(photos), "fotos"), (len(docs), "documentos"), ("✓" if all_ok else "✗", "evidencia íntegra")]:
        h.append(f'<div class="tile"><b>{val}</b><span>{lbl}</span></div>')
    h.append("</div>")

    h.append(f'<div class="rec {rec[1]}"><div class="score">{score}<span>de 100</span></div>'
             f"<div>Recomendación: {html.escape(rec[0])}"
             f"<small>El puntaje ordena la cola de trabajo según la cantidad y gravedad de las alertas; no es una probabilidad de fraude. "
             f"Las alertas no prueban fraude por sí solas: la decisión final es del liquidador.</small></div></div>")

    # resumen
    h.append("<section><h2>Resumen</h2>")
    if verified.accepted:
        h.append("<ul class=claims>")
        for s in verified.accepted:
            h.append(f"<li>{_link_cites(s, label)}</li>")
        h.append("</ul>")
        extra = len(findings) - len(verified.accepted)
        h.append(f'<p class="note">Se muestran las alertas más graves; {"hay " + str(extra) + " más en el detalle. " if extra > 0 else ""}'
                 f'Cada afirmación enlaza a la evidencia que la respalda. '
                 f'{len(verified.rejected)} afirmación(es) sin evidencia fueron descartadas automáticamente.</p>')
    else:
        h.append("<p>No se encontraron alertas con las verificaciones actuales.</p>")
    h.append("</section>")

    # miniaturas para reconocer a qué foto o documento se refiere cada hallazgo
    ev_ref = {}
    for p in photos:
        title = (p.meta.get("portal") or {}).get("title")
        ev_ref[p.ev] = (_thumb(case.evidence_dir / p.digest, (240, 180)), title or p.name, p.ev)
    for d in docs:
        path = case.evidence_dir / d.digest
        src = _thumb(path, (200, 240)) if d.meta.get("image_doc") else _pdf_thumb(path)
        ev_ref[d.ev] = (src, d.meta.get("title") or d.name, d.ev)

    # hallazgos por área
    if findings:
        h.append("<section><h2>Hallazgos por área</h2>")
        for cat in CATEGORY_ORDER + sorted({f.category for f in findings} - set(CATEGORY_ORDER)):
            fs = [f for f in findings if f.category == cat]
            if not fs:
                continue
            h.append(f'<div class="cat">{html.escape(cat or "Otros")} <span class="tag baja">{len(fs)}</span></div>')
            for f in fs:
                ref = next((ev_ref[e] for e in f.evidence if e in ev_ref), None)
                pic = ""
                if ref:
                    src, lbl, anchor = ref
                    pic = (f'<a class="fthumb" href="#ev-{anchor}" title="Ver {html.escape(lbl)}">'
                           + (f'<img src="{src}" alt="{html.escape(lbl)}">' if src else '<span class="noimg">sin vista previa</span>')
                           + f'<small>{html.escape(lbl)}</small></a>')
                g = for_rule(f.rule)
                tips = (f'<div class="tips"><p><b>Por qué importa:</b> {html.escape(g[0])}</p>'
                        f'<p><b>Qué hacer:</b> {html.escape(g[1])}</p></div>') if g else ""
                h.append(f'<div class="finding {f.severity}{" withpic" if pic else ""}">{pic}<div class="fbody">'
                         f'<span class="sev {f.severity}">{f.severity.upper()}</span>'
                         f"<b>{html.escape(f.title)}</b><p>{html.escape(f.summary)}</p>{tips}"
                         f"<p class=\"evid\">evidencia {cites(f.evidence)}</p></div></div>")
        h.append("</section>")

    # línea de tiempo forense
    events = net.get("timeline") or []
    if events:
        h.append('<section id="linea"><h2>Línea de tiempo forense</h2><ol class="tl">')
        day = None
        for e in events:
            d = e.ts.strftime("%d-%m-%Y")
            if d != day:
                day = d
                h.append(f'<li class="day">{_weekday(e.ts)} {d}</li>')
            anchor = f' id="ev-{e.ev}"' if e.ev and e.ev.split(":")[0] in chat_prefix else ""
            flags = "".join(f'<span class="flag">{html.escape(x)}</span>' for x in e.flags)
            cite = cites([e.ev]) if e.ev else ""
            hour = e.ts.strftime("%H:%M") if (e.ts.hour or e.ts.minute) else "—"
            h.append(f'<li class="ev k-{e.kind}{" bad" if e.flags else ""}"{anchor}><div class="t">{hour}<small>{html.escape(e.trust)}</small></div>'
                     f'<span class="dot"></span><div class="what"><span class="kind">{KIND_LABEL.get(e.kind, e.kind)}</span>'
                     f'<b>{html.escape(e.title)}</b>{flags} {cite}'
                     f'{"<p>" + html.escape(e.detail) + "</p>" if e.detail else ""}</div></li>')
        h.append('</ol><p class="note">Cada hecho muestra de dónde sale su hora: la cámara, el servidor (captura segura), los '
                 'metadatos del documento o el chat. En rojo, los hechos que no pueden ser ciertos a la vez.</p></section>')

    # red de siniestros
    h.append("<section><h2>Red de siniestros</h2>")
    if net["neighbors"] or net["group"]:
        h.append(_net_svg(net))
        h.append('<div class="scroll"><table><tr><th>Siniestro</th><th>Asegurado</th><th>Fecha</th><th>Vínculo</th><th>Estado</th></tr>')
        for num in sorted(set(net["neighbors"]) | set(net["group"])):
            nb = net["neighbors"].get(num)
            info = net["group_info"].get(num, {})
            why = ", ".join(nb["why"]) if nb else "indirecto (a través de otro siniestro)"
            lv = (nb or info).get("level")
            asg = (nb or {}).get("asegurado") or info.get("asegurado", "")
            fecha = _fmt_date((nb or {}).get("fecha"))[:10]
            h.append(f"<tr><td><b>{html.escape(num)}</b></td><td>{html.escape(asg)}</td><td>{fecha}</td>"
                     f"<td>{html.escape(why)}</td><td>{LEVEL_TEXT.get(lv, '')}</td></tr>")
        h.append("</table></div>")
        h.append('<p class="note">Color del punto: rojo, derivado a investigación; ámbar, revisión manual; verde, sin alertas al momento de su análisis. Línea roja: vínculo directo con este siniestro. Se consideran teléfono, correo, cuenta bancaria '
                 "y dirección compartidos entre asegurados distintos, además de fotos, documentos y relatos repetidos.</p>")
    else:
        h.append("<p>No se encontraron vínculos con otros siniestros del registro.</p>")
    h.append("</section>")

    # declaración
    h.append('<section id="decl"><h2>Declaración</h2><div class="cols">')
    groups = [
        ("Siniestro", [("N° siniestro", decl.get("numero")), ("Fecha y hora", _fmt_date(decl.get("fecha_siniestro"))),
                       ("Denunciado", _fmt_date(decl.get("fecha_denuncia"))), ("Lugar", decl.get("lugar")),
                       ("Taller", decl.get("taller")), ("Testigos", decl.get("testigos")),
                       ("Parte policial", decl.get("parte_policial"))]),
        ("Asegurado", [("Nombre", decl.get("asegurado")), ("RUT", decl.get("rut")), ("Teléfono", decl.get("telefono")),
                       ("Correo", decl.get("email")), ("Dirección", decl.get("direccion")),
                       ("Cuenta para pago", decl.get("cuenta_bancaria")), ("Patente", decl.get("patente"))]),
        ("Póliza", [("N° póliza", decl.get("poliza")), ("Inicio", _fmt_date(decl.get("inicio_poliza"))),
                    ("Vencimiento", _fmt_date(decl.get("fin_poliza"))), ("Cambio de cobertura", _fmt_date(decl.get("cambio_cobertura"))),
                    ("Suma asegurada", decl.get("suma_asegurada")), ("Deducible", decl.get("deducible")),
                    ("Monto reclamado", decl.get("monto_reclamado"))]),
    ]
    for title, rows in groups:
        rows = [(k, v) for k, v in rows if v not in (None, "")]
        if rows:
            h.append(f"<div><h3>{title}</h3><dl class=decl>")
            h.extend(f"<dt>{k}</dt><dd>{html.escape(str(v))}</dd>" for k, v in rows)
            h.append("</dl></div>")
    h.append("</div>")
    if decl.get("descripcion"):
        h.append(f'<h3 style="font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:16px 0 0">Relato del asegurado</h3>'
                 f'<p class="relato">{html.escape(decl["descripcion"])}</p>')
    h.append("</section>")

    # documentos
    if docs:
        h.append('<section><h2>Documentos</h2><div class="scroll"><table><tr><th>Documento</th><th>Software</th>'
                 "<th>Creado</th><th>Modificado</th><th>Versiones</th><th>Alertas</th></tr>")
        for d in docs:
            m = d.meta
            tags = "".join(f'<span class="tag {f.severity}">{html.escape(f.title.split(" (")[0])}</span>'
                           for f in by_ev.get(d.ev, [])) or '<span class="tag ok">Sin alertas</span>'
            h.append(f'<tr id="ev-{d.ev}"><td><b>{html.escape(m.get("title") or d.name)}</b>'
                     f'{"<br><small>" + html.escape(d.name) + "</small>" if m.get("title") else ""} <a class="cite" href="#ev-{d.ev}">{d.ev.split(":")[0]}</a></td>'
                     f"<td>{html.escape(', '.join(m.get('tools', [])) or '—')}</td><td>{_fmt_date(m.get('created')) or '—'}</td>"
                     f"<td>{_fmt_date(m.get('modified')) or '—'}</td><td>{_version_cell(d)}</td><td>{tags}</td></tr>")
        h.append("</table></div>")
        for d in docs:
            for ch in (d.meta.get("versions") or {}).get("changes", []):
                h.append(f'<p style="margin:14px 0 0"><b>{html.escape(d.name)}</b>: qué cambió de la versión {ch["from"]} '
                         f'a la {ch["to"]}{" (" + html.escape(ch["producer"]) + ")" if ch.get("producer") else ""}</p><div class="diff">')
                h.extend(f'<div class="rm">− {html.escape(x)}</div>' for x in ch["removed"][:12])
                h.extend(f'<div class="ad">+ {html.escape(x)}</div>' for x in ch["added"][:12])
                h.append("</div>")
        h.append("</section>")

    # fotos
    if photos:
        h.append("<section><h2>Fotos</h2><div class=gallery>")
        for p in photos:
            m = p.meta
            src = _thumb(case.evidence_dir / p.digest)
            cam = " ".join(filter(None, [m.get("make"), m.get("model")])) or "sin datos de cámara"
            if m.get("secure_capture"):
                cam = "Captura segura (cámara en vivo, hora del servidor)"
            elif m.get("portal"):
                cam += " · subida por el asegurado (archivo original)"
            when = _fmt_date(m.get("taken")) or "sin fecha"
            where = "sin GPS"
            if m.get("gps") and decl.get("lat") is not None:
                km = km_between((decl["lat"], decl["lon"]), tuple(m["gps"]))
                where = f"GPS a {km * 1000:.0f} m del lugar declarado" if km < 1 else f"GPS a {km:.1f} km del lugar declarado"
            tags = "".join(f'<span class="tag {f.severity}">{html.escape(f.title.split(" (")[0])}</span>'
                           for f in by_ev.get(p.ev, [])) or '<span class="tag ok">Sin alertas</span>'
            img = f'<img src="{src}" alt="{html.escape(p.name)}">' if src else '<img alt="">'
            ptitle = (m.get("portal") or {}).get("title")
            h.append(f'<div class="photo" id="ev-{p.ev}">{img}<div class="body"><b>{html.escape(ptitle or p.name)}</b> '
                     f'<a class="cite" href="#ev-{p.ev}">{p.ev.split(":")[0]}</a>'
                     f'<div class="meta">{html.escape(cam)} · {when}<br>{where}'
                     f'{"<br>Software: " + html.escape(m["software"]) if m.get("software") else ""}</div>{tags}</div></div>')
        h.append("</div></section>")

    h.append(_integrity_html(chain_ok, chain_msg, ev_ok, ev_problems, seal_txt))
    h.append(_custody_html(entries))
    h.append("<footer>Generado por Evidex by Zelekpress · v1.1 · prototipo · las alertas requieren validación humana</footer></div></html>")
    return "\n".join(h).replace(f'href="#ev-{decl_ev}"', 'href="#decl"')
