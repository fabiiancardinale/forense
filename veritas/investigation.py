"""Expedientes de investigación y auditorías de informes.

Expediente: el investigador carga los datos del siniestro, las alertas de la compañía, las
entrevistas transcritas y los documentos. Veritas detecta contradicciones entre declarantes y
contra los documentos, sugiere evidencia para cada alerta, revisa el informe antes de enviarlo
y lo genera con la estructura habitual, citando la pregunta o documento que respalda cada punto.

Auditoría: se sube un informe PDF ya terminado y Veritas lo revisa (ver report_audit.py).

Todo queda en la cadena de custodia: entrevistas, documentos, respuestas a alertas, conclusión
y cada cambio, con autor y hora.
"""
from __future__ import annotations

import html
import json
import re
import tempfile
from pathlib import Path

from . import assistant
from . import interviews as I
from . import report_audit as RA
from .case import Case
from .detections import Finding
from .timeline import Timeline

STATES = ["Descartado", "Acreditado", "Acreditado con matices", "No descartado", "Indeterminado", "Confirmado"]
RECOMMENDATIONS = ["Aprobar el pago", "Aprobar con observaciones", "Rechazar el reclamo", "Continuar la investigación"]
SEV_ORDER = {"alta": 0, "media": 1, "baja": 2}


# ---- creación ----------------------------------------------------------------------------
def create(workdir: Path, cid: str, data: dict, interviews: list[dict], files: list[Path], actor: str = "investigador") -> Case:
    case = Case.create(Path(workdir) / cid, f"Investigación {data.get('numero', cid)}", analyst=actor, kind="investigacion")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "expediente.json"
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        case.add_evidence(p, analyst=actor, note="expediente")
        for i, iv in enumerate(interviews, 1):
            q = Path(td) / f"entrevista_{i}.json"
            q.write_text(json.dumps(iv, indent=2, ensure_ascii=False), encoding="utf-8")
            case.add_evidence(q, analyst=actor, note="entrevista")
    for f in files:
        case.add_evidence(f, analyst=actor, note="documento")
    return case


def create_audit(workdir: Path, cid: str, pdf: Path, actor: str = "revisor", original_name: str | None = None) -> Case:
    case = Case.create(Path(workdir) / cid, f"Auditoría {original_name or pdf.name}", analyst=actor, kind="auditoria")
    case.add_evidence(pdf, analyst=actor, note="informe")
    return case


# ---- lectura ------------------------------------------------------------------------------
def _pdf_text(path: Path, max_pages: int = 15) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages[:max_pages])
    except Exception:
        return ""


def load(case: Case) -> dict:
    data, ivs, docs = {}, [], []
    for e in case.active_evidence():
        path, note, name = case.evidence_dir / e["subject"], e["data"].get("note"), e["data"]["original_name"]
        if note == "expediente":
            data = json.loads(path.read_text(encoding="utf-8"))
        elif note == "entrevista":
            raw = json.loads(path.read_text(encoding="utf-8"))
            iv = I.Interview(raw.get("declarante", ""), raw.get("rol", ""), raw.get("fecha", ""),
                             I.parse_text(raw.get("texto", "")), e["subject"][:8], len(ivs) + 1)
            ivs.append(iv)
        elif note in ("documento", "informe"):
            text = _pdf_text(path) if name.lower().endswith(".pdf") else ""
            docs.append({"name": name, "digest": e["subject"], "ev": f"{e['subject'][:8]}:1", "path": path,
                         "facts": I.doc_facts_from_text(name, f"{e['subject'][:8]}:1", text)})
    responses: dict[int, dict] = {}
    conclusion = None
    for e in case.ledger.entries():
        if e["action"] == "alert_response":
            responses[int(e["subject"])] = {**e["data"], "actor": e["actor"], "ts": e["ts"]}
        elif e["action"] == "conclusion":
            conclusion = {**e["data"], "actor": e["actor"], "ts": e["ts"]}
    return {"data": data, "interviews": ivs, "docs": docs, "responses": responses, "conclusion": conclusion}


def save_response(case: Case, idx: int, estado: str, hallazgo: str, evidencia: list[str], actor: str) -> None:
    case.ledger.append(actor or "investigador", "alert_response", str(idx),
                       {"estado": estado, "hallazgo": hallazgo, "evidencia": evidencia})


def save_conclusion(case: Case, recomendacion: str, texto: str, actor: str) -> None:
    case.ledger.append(actor or "investigador", "conclusion", recomendacion, {"recomendacion": recomendacion, "texto": texto})


# ---- análisis -------------------------------------------------------------------------------
def evidence_index(x: dict) -> dict[str, dict]:
    """id de evidencia -> {label, text, kind} para citar y mostrar."""
    idx = {}
    for iv in x["interviews"]:
        for qa in iv.items:
            idx[iv.ev(qa.n)] = {"label": f"E{iv.index}·P{qa.n}", "who": iv.declarante, "q": qa.q, "text": qa.a, "kind": "qa"}
    for d in x["docs"]:
        idx[d["ev"]] = {"label": d["name"], "who": "", "q": "", "text": "", "kind": "doc"}
    return idx


def analyze(case: Case) -> dict:
    x = load(case)
    t0 = x["data"].get("fecha_ocurrencia")
    findings = I.compare(x["interviews"], t0)
    findings += I.cross_documents(x["interviews"], [d["facts"] for d in x["docs"]], x["data"].get("rut_asegurado"))
    findings.sort(key=lambda f: SEV_ORDER[f.severity])
    idx = evidence_index(x)
    # eventos citables para el verificador de afirmaciones
    db = case.root / "timeline.db"
    tl = Timeline(db, fresh=True)
    try:
        for eid, v in idx.items():
            tl.add_event(eid, x["data"].get("fecha_ocurrencia", ""), v["who"] or v["label"], v["kind"], None, v["who"],
                         (v["q"] + " " + v["text"])[:500])
        verified = assistant.summarize(findings, tl)
    finally:
        tl.close()
    return {**x, "findings": findings, "index": idx, "verified": verified, "suggestions": suggestions(x, findings)}


def suggestions(x: dict, findings: list[Finding]) -> dict[int, list[str]]:
    """Para cada alerta, las respuestas de entrevistas y documentos más relacionados."""
    out = {}
    stop = {"para", "pedir", "validar", "posible", "indica", "que", "fue", "del", "los", "las", "una", "con", "informacion"}
    for i, alert in enumerate(x["data"].get("alertas", []), 1):
        words = {w for w in I.tokens(alert) if len(w) > 3 and w not in stop}
        extra = set()
        a = I.norm(alert)
        if re.search(r"comercial|app|aplicaci|uber|plataforma", a):
            extra |= {"aplicacion", "transporte", "uber", "cabify", "pasajeros", "habitualmente", "uso"}
        if re.search(r"medic|doctor|clinica|turno|hora", a):
            extra |= {"clinica", "medica", "consulta", "doctor", "hora", "kinesiologo", "presupuesto", "bono", "atencion"}
        if re.search(r"direccion|trayecto|ruta", a):
            extra |= {"direccion", "domicilio", "salieron", "clinica", "regreso"}
        words |= extra
        scored = []
        for iv in x["interviews"]:
            for qa in iv.items:
                t = set(I.tokens(qa.q + " " + qa.a))
                s = len(words & t)
                if s:
                    scored.append((s, iv.ev(qa.n)))
        for d in x["docs"]:
            if words & set(I.tokens(d["name"])):
                scored.append((2, d["ev"]))
        out[i] = [e for _, e in sorted(scored, reverse=True)[:6]]
    return out


def review(a: dict) -> list[Finding]:
    """Revisión previa al envío: alertas sin respuesta o sin evidencia, conclusión, contradicciones no abordadas."""
    out: list[Finding] = []
    alerts = a["data"].get("alertas", [])
    cited = set()
    for i, alert in enumerate(alerts, 1):
        r = a["responses"].get(i)
        if not r or not r.get("estado"):
            out.append(Finding("review_missing", "media", "Alerta sin responder", f"La alerta {i} (\"{alert}\") no tiene estado ni hallazgo.", [], "", "Revisión previa"))
            continue
        cited |= set(r.get("evidencia", []))
        if not r.get("evidencia"):
            out.append(Finding("review_no_evidence", "media", "Respuesta sin evidencia citada",
                               f"La respuesta a la alerta {i} (\"{alert}\") no cita ninguna entrevista ni documento.", [], "", "Revisión previa"))
    for f in a["findings"]:
        if f.severity in ("alta", "media") and not (set(f.evidence) & cited):
            out.append(Finding("review_unaddressed", "media", f"Contradicción no abordada: {f.title}",
                               f.summary + " Ninguna respuesta a las alertas cita esta evidencia.", f.evidence, "", "Revisión previa"))
    c = a["conclusion"]
    if not c:
        out.append(Finding("review_no_conclusion", "media", "Falta la conclusión", "El expediente no tiene recomendación final.", [], "", "Revisión previa"))
    elif "rechaz" in I.norm(c["recomendacion"]):
        states = [I.norm(r.get("estado", "")) for r in a["responses"].values()]
        if not any(s.startswith(("confirmad", "acreditado")) and not s.startswith("acreditado con matices") for s in states):
            out.append(Finding("review_weak_rejection", "media", "Rechazo sin un hecho acreditado",
                               "Se recomienda rechazar, pero ninguna alerta quedó confirmada o acreditada; las que sostienen el rechazo están "
                               "\"no descartadas\" o \"indeterminadas\". La ley presume que el siniestro está cubierto y la carga de probar "
                               "la exclusión recae en la aseguradora: conviene fundarlo en un hecho acreditado o revisarlo con el área legal.",
                               [], "", "Revisión previa"))
    return out


# ---- informe ---------------------------------------------------------------------------------
REPORT_CSS = """
@page{size:A4;margin:22mm 18mm}
body{font:11.5pt/1.5 Georgia,'Times New Roman',serif;color:#111;max-width:820px;margin:24px auto;padding:0 20px}
.brand{text-align:center;letter-spacing:.35em;font-weight:700;font-size:10pt;margin-top:10px}
.brand small{display:block;letter-spacing:0;font-weight:400;font-style:italic;color:#555}
h1{text-align:center;font-size:20pt;letter-spacing:.08em;margin:60px 0 6px}
.sub{text-align:center;color:#444;margin-bottom:40px}
h2{font-size:12.5pt;letter-spacing:.12em;text-transform:uppercase;border-bottom:1.5px solid #111;padding-bottom:4px;margin-top:34px;page-break-after:avoid}
h3{font-size:11.5pt;margin:18px 0 4px}
table{border-collapse:collapse;width:100%;margin:8px 0 14px;font-size:10.5pt}
td,th{border:1px solid #bbb;padding:5px 8px;vertical-align:top;text-align:left}th{background:#eee}
.qa{margin:0 0 10px}.qa b{display:block}.qa p{margin:2px 0 0}
.who{background:#fff3a8;font-weight:700;padding:1px 4px}
.cite{font:9pt ui-monospace,monospace;color:#0b4a7a;text-decoration:none;background:#eef3f9;padding:0 3px;border-radius:3px}
.rec{border:1.5px solid #111;text-align:center;font-weight:700;padding:6px;margin:10px 0}
.sev{font:bold 8.5pt system-ui,sans-serif;padding:1px 5px;border-radius:3px}
.sev.alta{background:#fdecea;color:#b3261e}.sev.media{background:#fff4e0;color:#8a5300}.sev.baja{background:#eee;color:#555}
.note{color:#555;font-size:10pt}
.cover{page-break-after:always}
@media print{.noprint{display:none}a{color:inherit}}
"""


def _cl(iso: str | None) -> str:
    """Fecha ISO a formato chileno dd/mm/aaaa hh:mm."""
    if not iso:
        return ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?", iso)
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" + (f" {m.group(4)}:{m.group(5)}" if m.group(4) else "") if m else iso


def build_report(case: Case, a: dict, empresa: str = "") -> str:
    d = a["data"]
    idx = a["index"]

    def cites(ids):
        return " ".join(f'<a class="cite" href="#{re.sub(r"[^0-9a-z]", "", e)}">{html.escape(idx.get(e, {}).get("label", e))}</a>' for e in ids)

    e = html.escape
    h = [f"<!doctype html><html lang=es><meta charset=utf-8><title>Informe {e(d.get('numero', ''))}</title><style>{REPORT_CSS}</style>"]
    h.append('<p class="noprint note">Para obtener el PDF: imprima esta página (Ctrl+P) y elija "Guardar como PDF".</p>')
    h.append(f'<div class="cover"><div class="brand">{e(empresa.upper() or "INFORME DE INVESTIGACIÓN")}<small>Análisis de siniestros</small></div>')
    h.append(f"<h1>INFORME DE INVESTIGACIÓN<br>DE SINIESTRO VEHICULAR</h1><div class=sub>Siniestro N° {e(d.get('numero', ''))}</div>")
    rows = [("Aseguradora", d.get("aseguradora")), ("Tipo de siniestro", d.get("tipo")), ("Fecha de ocurrencia", _cl(d.get("fecha_ocurrencia"))),
            ("Vehículo", d.get("vehiculo")), ("Fecha de emisión", _cl(case.ledger.entries()[-1]["ts"]) + " UTC")]
    h.append("<table>" + "".join(f"<tr><th>{k}</th><td>{e(str(v or '—'))}</td></tr>" for k, v in rows) + "</table>")
    h.append('<p class="note" style="text-align:center">Documento de carácter confidencial, de uso exclusivo para la evaluación del siniestro individualizado.</p></div>')

    h.append("<h2>1. Datos del siniestro</h2><table>")
    for k, v in [("Fecha de ocurrencia", _cl(d.get("fecha_ocurrencia"))), ("Dirección", d.get("direccion")),
                 ("Comuna / Ciudad", d.get("comuna")), ("Vehículo", d.get("vehiculo")), ("Patente", d.get("patente"))]:
        h.append(f"<tr><th>{k}</th><td>{e(str(v or '—'))}</td></tr>")
    h.append("</table>")
    if d.get("descripcion"):
        h.append(f"<h3>Descripción registrada</h3><p>{e(d['descripcion'])}</p>")
    h.append("<h3>Alertas de la compañía</h3><table><tr><th>N°</th><th>Alerta</th></tr>" +
             "".join(f"<tr><td>{i}</td><td>{e(al)}</td></tr>" for i, al in enumerate(d.get("alertas", []), 1)) + "</table>")

    h.append("<h2>2. Entrevistas realizadas</h2>")
    for iv in a["interviews"]:
        h.append(f'<h3><span class="who">{e(iv.declarante)} — {e(iv.rol)}</span></h3><p class="note">Fecha de entrevista: {e(iv.fecha)}</p>')
        for qa in iv.items:
            anchor = re.sub(r"[^0-9a-z]", "", iv.ev(qa.n))
            h.append(f'<div class="qa" id="{anchor}"><b>{qa.n}. {e(qa.q)}</b><p>{e(qa.a)}</p></div>')

    h.append("<h2>3. Contradicciones detectadas</h2>")
    if a["findings"]:
        h.append("<table><tr><th>Tema</th><th>Detalle</th><th>Evidencia</th></tr>")
        for f in a["findings"]:
            h.append(f'<tr><td><span class="sev {f.severity}">{f.severity.upper()}</span> {e(f.title)}</td><td>{e(f.summary)}</td><td>{cites(f.evidence)}</td></tr>')
        h.append("</table><p class=note>Detectadas automáticamente comparando las declaraciones y los documentos; cada una cita la pregunta o documento de origen.</p>")
    else:
        h.append("<p>No se detectaron contradicciones entre las declaraciones ni con los documentos.</p>")

    h.append("<h2>4. Respuesta a las alertas</h2><table><tr><th>Alerta</th><th>Estado y hallazgo</th><th>Evidencia</th></tr>")
    for i, al in enumerate(d.get("alertas", []), 1):
        r = a["responses"].get(i, {})
        h.append(f"<tr><td>{e(al)}</td><td><b>{e(r.get('estado', 'Pendiente'))}.</b> {e(r.get('hallazgo', ''))}</td><td>{cites(r.get('evidencia', []))}</td></tr>")
    h.append("</table>")

    c = a["conclusion"] or {}
    h.append("<h2>5. Conclusión y recomendación</h2>")
    h.append(f'<div class="rec">SE RECOMIENDA: {e((c.get("recomendacion") or "PENDIENTE").upper())}</div><p>{e(c.get("texto", ""))}</p>')

    h.append(f"<h2>6. Documentación revisada</h2><p>Se revisaron {len(a['docs'])} documento(s) anexos al expediente.</p>")
    h.append("<table><tr><th>N°</th><th>Documento</th><th>Huella SHA-256</th></tr>" +
             "".join(f'<tr id="{re.sub(r"[^0-9a-z]", "", doc["ev"])}"><td>{i}</td><td>{e(doc["name"])}</td><td><code>{doc["digest"][:16]}…</code></td></tr>'
                     for i, doc in enumerate(a["docs"], 1)) + "</table>")

    from .ledger import verify_chain
    ok, msg = verify_chain(case.ledger.entries())
    h.append("<h2>7. Metodología y alcance</h2>")
    h.append(f"<p>El informe se elaboró sobre el expediente del siniestro: {len(a['docs'])} documento(s) y {len(a['interviews'])} entrevista(s). "
             "La detección de contradicciones se realizó con herramientas automatizadas que citan la fuente de cada afirmación; su resultado es un "
             "insumo de trabajo que no reemplaza el criterio profesional. Las conclusiones fueron revisadas y asumidas por quien firma.</p>")
    h.append(f"<p class=note>Cadena de custodia: {e(msg)} ({'verificable' if ok else 'con problemas'}). Cada entrevista, documento, respuesta y "
             "conclusión quedó registrada con autor, hora y huella digital.</p>")
    if c:
        h.append(f"<table><tr><th>Elaborado por</th><td>{e(c.get('actor', ''))}</td></tr><tr><th>Fecha</th><td>{e(_cl(c.get('ts', '')))} UTC</td></tr></table>")
    return "\n".join(h)


# ---- auditoría --------------------------------------------------------------------------------
def run_audit(case: Case) -> dict:
    x = load(case)
    doc = x["docs"][0]
    rep = RA.read_pdf(doc["path"])
    prefix = doc["digest"][:8]
    findings = RA.audit(rep, prefix)
    idx = {}
    for iv in rep.interviews:
        for qa in iv.items:
            idx[iv.ev(qa.n)] = {"label": f"E{iv.index}·P{qa.n}", "who": iv.declarante, "q": qa.q, "text": qa.a, "page": qa.page}
    for p in range(1, rep.pages + 1):
        idx[RA.page_ev(prefix, p)] = {"label": f"pág. {p}", "who": "", "q": "", "text": "", "page": p}
    return {"report": rep, "findings": findings, "index": idx, "matrix": RA.topic_matrix(rep), "name": doc["name"], "digest": doc["digest"]}


# ---- listados, ejemplo y vista de auditoría -----------------------------------------------------
DEMO_DIR = Path(__file__).resolve().parent.parent / "demo" / "investigacion_demo"


def list_cases(workdir: Path, kind: str) -> list[Case]:
    out = []
    for d in sorted(Path(workdir).iterdir()) if Path(workdir).is_dir() else []:
        c = Case(d)
        if c.meta_path.exists() and c.kind == kind:
            out.append(c)
    return out


def load_demo(workdir: Path) -> list[str]:
    """Carga el expediente ficticio (con parte del trabajo hecho) y la auditoría del informe ficticio."""
    done = []
    if not DEMO_DIR.exists():
        return done
    data = json.loads((DEMO_DIR / "expediente.json").read_text(encoding="utf-8"))
    cid = data["numero"]
    if not (Path(workdir) / cid / "case.json").exists():
        ivs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(DEMO_DIR.glob("entrevista_*.json"))]
        case = create(workdir, cid, data, ivs, sorted((DEMO_DIR / "documentos").iterdir()), actor="Analista demo")
        a = analyze(case)
        ev = {v["label"]: k for k, v in a["index"].items()}
        save_response(case, 1, "No descartado", "El asegurado no puede descartar el uso en aplicaciones y el conductor lo niega; "
                      "ambos autorizaron verbalmente la consulta a las plataformas.", [ev["E1·P10"], ev["E2·P9"]], "Analista demo")
        save_response(case, 3, "No descartado", "Firmaron la carta APP marcando \"No autorizo\" pese a autorizar verbalmente.",
                      [ev["E1·P11"], ev["E2·P10"]], "Analista demo")
        save_conclusion(case, "Rechazar el reclamo", "La alerta de uso comercial no pudo ser descartada con los antecedentes disponibles.",
                        "Analista demo")
        done.append(cid)
    pdf = DEMO_DIR / "informe_para_auditar.pdf"
    if pdf.exists():
        from .case import sha256_file
        aid = "AUD-" + sha256_file(pdf)[:8]
        if not (Path(workdir) / aid / "case.json").exists():
            c = create_audit(workdir, aid, pdf, actor="Revisor demo")
            r = run_audit(c)
            c.ledger.append("veritas", "audit_run", r["name"], _audit_counts(r["findings"]))
            c.ledger.seal()
            done.append(aid)
    return done


def _audit_counts(findings) -> dict:
    return {s: sum(1 for f in findings if f.severity == s) for s in ("alta", "media", "baja")}


def audit_html(r: dict) -> str:
    """Fragmento HTML con el resultado de la auditoría (se usa en la interfaz y en el informe descargable)."""
    e = html.escape
    rep, idx = r["report"], r["index"]
    counts = _audit_counts(r["findings"])
    ready = counts["alta"] == 0 and counts["media"] == 0
    h = [f'<div class="verdict {"ok" if ready else ("bad" if counts["alta"] else "warn")}"><b>'
         f'{"Listo para enviar" if ready else "Revisar antes de enviar"}</b><span>{counts["alta"]} alta · {counts["media"]} media · '
         f'{counts["baja"]} baja</span></div>']
    h.append('<div class="grid4">' + "".join(f'<div class="card tile"><b>{v}</b><span>{k}</span></div>' for k, v in [
        ("páginas", rep.pages), ("entrevistas", len(rep.interviews)), ("preguntas transcritas", sum(len(i.items) for i in rep.interviews)),
        ("alertas de la compañía", len(rep.alerts)), ("respuestas a alertas", len(rep.responses)), ("documentos", len(rep.documents))]) + "</div>")
    if rep.recommendation:
        h.append(f'<p class="hint">Recomendación del informe: <b>{e(rep.recommendation)}</b></p>')
    cats = []
    for f in r["findings"]:
        if f.category not in cats:
            cats.append(f.category)
    for cat in cats:
        h.append(f'<h3 class="cat">{e(cat)}</h3>')
        for f in [x for x in r["findings"] if x.category == cat]:
            quotes = []
            for ev in f.evidence:
                v = idx.get(ev, {})
                if v.get("text") or v.get("q"):
                    quotes.append(f'<div class="quote"><span class="cite">{e(v["label"])} · pág. {v.get("page") or "?"}</span> '
                                  f'<b>{e(v["who"])}</b> — <i>{e(v["q"][:140])}</i><br>“{e(v["text"][:320])}”</div>')
                elif v:
                    quotes.append(f'<span class="cite">{e(v["label"])}</span> ')
            h.append(f'<div class="finding {f.severity}"><span class="sev {f.severity}">{f.severity.upper()}</span><b>{e(f.title)}</b>'
                     f'<p>{e(f.summary)}</p>{"".join(quotes)}</div>')
    if r["matrix"]:
        h.append('<h3 class="cat">Qué dice cada declarante</h3><div class="scroll"><table><tr><th>Tema</th>' +
                 "".join(f"<th>{e(iv.declarante)}<br><span class='hint'>{e(iv.rol)}</span></th>" for iv in rep.interviews) + "</tr>")
        for title, cells in r["matrix"]:
            h.append(f"<tr><td><b>{e(title)}</b></td>" + "".join(f"<td>{e(c)}</td>" for c in cells) + "</tr>")
        h.append("</table></div>")
    h.append('<p class="hint">Revisión automática: señala puntos a verificar, no reemplaza la lectura del investigador. '
             'Las entrevistas se identifican como E1, E2… y las preguntas como P1, P2…, según su orden en el informe.</p>')
    return "\n".join(h)


AUDIT_CSS = """
:root{--ink:#16202c;--muted:#5b6673;--line:#e3e7ec;--bg:#f6f8fa;--card:#fff;--accent:#0f4c81;--red:#b3261e;--redbg:#fdecea;
--amb:#8a5300;--ambbg:#fff4e0;--grn:#146c2e;--grnbg:#e7f5ec}
body{margin:0;font:14.5px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;color:var(--ink);background:var(--bg)}
main{max-width:1100px;margin:0 auto;padding:24px 20px 60px}h1{font-size:22px;margin:0 0 4px}
.verdict{display:flex;justify-content:space-between;align-items:center;border-radius:10px;padding:14px 18px;margin:14px 0;font-size:16px}
.verdict.ok{background:var(--grnbg);color:var(--grn)}.verdict.warn{background:var(--ambbg);color:var(--amb)}.verdict.bad{background:var(--redbg);color:var(--red)}
.verdict span{font-size:13px;font-weight:600}
.grid4{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}.tile b{display:block;font-size:20px}.tile span{color:var(--muted);font-size:12.5px}
h3.cat{font-size:12.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:20px 0 6px}
.finding{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--line);border-radius:0 8px 8px 0;padding:10px 14px;margin:8px 0}
.finding.alta{border-left-color:var(--red)}.finding.media{border-left-color:#c77d00}.finding p{margin:4px 0 6px}
.sev{font-size:11px;font-weight:700;padding:2px 7px;border-radius:4px;margin-right:8px}
.sev.alta{background:var(--redbg);color:var(--red)}.sev.media{background:var(--ambbg);color:var(--amb)}.sev.baja{background:#eef1f4;color:var(--muted)}
.quote{background:var(--bg);border-radius:6px;padding:6px 10px;margin:4px 0;font-size:13px}
.cite{font:11.5px ui-monospace,monospace;background:#eef3f9;color:var(--accent);border-radius:4px;padding:1px 5px}
table{border-collapse:collapse;width:100%;background:var(--card)}th,td{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
th{color:var(--muted);font-size:12.5px}.hint{color:var(--muted);font-size:12.5px}.scroll{overflow-x:auto}
"""


def audit_page(r: dict) -> str:
    """Auditoría como página HTML independiente (para descargar, archivar o enviar internamente)."""
    return (f"<!doctype html><html lang=es><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>Auditoría {html.escape(r['name'])}</title><style>{AUDIT_CSS}</style><main><h1>Auditoría de informe</h1>"
            f"<p class=hint>{html.escape(r['name'])} · huella SHA-256 {r['digest'][:16]}… · generado por Veritas</p>{audit_html(r)}</main></html>")
