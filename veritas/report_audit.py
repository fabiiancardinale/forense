"""Auditoría de informes de investigación de siniestros (PDF) antes de enviarlos a la compañía.

Lee informes con la estructura habitual (datos del siniestro, alertas de la compañía,
entrevistas transcritas, resumen, respuesta a las alertas, hallazgos, conclusión, documentos)
y revisa:
  1. Contradicciones entre entrevistados, indicando si el informe ya las aborda.
  2. Afirmaciones del propio informe que se contradicen entre secciones.
  3. Errores probables de transcripción (respuestas marcadas como preguntas, cortes).
  4. Que cada alerta de la compañía tenga respuesta y estado.
  5. Que la conclusión se apoye en hechos acreditados y no solo en alertas "no descartadas".
  6. Forma: filas vacías, nombres escritos de dos maneras, fechas fuera de orden.

Las entrevistas se reconocen por el formato: preguntas numeradas en negrita y respuestas en
texto normal. Si el PDF viene escaneado (imagen), primero requiere OCR.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import interviews as I
from .detections import Finding

PAGE_BASE = 900000
SKIP = re.compile(r"^(Informe de investigaci[oó]n de siniestro|P[aá]gina \d+( de \d+)?$)")
HEADING = re.compile(r"^(\d{1,2})\.\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ]{3,})$")
STATUS = re.compile(r"^(no descartad[oa]|descartad[oa]|acreditad[oa](?: con matices)?|no acreditad[oa]|indeterminad[oa]|"
                    r"confirmad[oa]|parcialmente acreditad[oa]|pendiente)", re.I)


@dataclass
class Line:
    page: int
    text: str
    bold: bool


@dataclass
class ParsedReport:
    lines: list[Line]
    tables: list[tuple[int, list[list]]]
    meta: dict = field(default_factory=dict)
    sections: dict[str, dict] = field(default_factory=dict)  # título -> {"n", "pages", "text"}
    interviews: list[I.Interview] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    responses: list[dict] = field(default_factory=list)      # {"alerta", "hallazgo", "estado", "page"}
    findings_table: list[dict] = field(default_factory=list)  # {"hallazgo", "evidencia", "page"}
    documents: list[str] = field(default_factory=list)
    conclusion: str = ""
    recommendation: str = ""
    pages: int = 0


def read_pdf(path: Path) -> ParsedReport:
    import pdfplumber  # pip install pdfplumber
    lines, tables = [], []
    with pdfplumber.open(str(path)) as pdf:
        n = len(pdf.pages)
        for i, p in enumerate(pdf.pages, start=1):
            for ln in p.extract_text_lines(return_chars=True):
                txt = ln["text"].strip()
                if not txt or SKIP.match(txt):
                    continue
                chars = ln["chars"]
                bold = sum("Bold" in c.get("fontname", "") for c in chars) > len(chars) / 2
                lines.append(Line(i, txt, bold))
            for t in p.extract_tables():
                tables.append((i, [[(c or "").replace("\n", " ").strip() for c in row] for row in t]))
    rep = ParsedReport(lines, tables, pages=n)
    _structure(rep)
    return rep


def _structure(rep: ParsedReport) -> None:
    # secciones
    current = "Portada"
    rep.sections[current] = {"n": 0, "pages": set(), "text": []}
    for ln in rep.lines:
        m = HEADING.match(ln.text)
        if ln.bold and m:
            current = m.group(2).strip().title()
            rep.sections[current] = {"n": int(m.group(1)), "pages": set(), "text": []}
            continue
        rep.sections[current]["pages"].add(ln.page)
        rep.sections[current]["text"].append(ln.text)
    for s in rep.sections.values():
        s["text"] = " ".join(s["text"])
        s["pages"] = sorted(s["pages"])
    # datos generales
    full = " ".join(ln.text for ln in rep.lines)
    if m := re.search(r"Siniestro N[°º]\s*([\w-]+)", full):
        rep.meta["numero"] = m.group(1)
    for page, rows in rep.tables:
        for row in rows:
            if len(row) >= 2 and row[0]:
                key = I.norm(row[0])
                if key in ("fecha de ocurrencia", "fecha de emision", "aseguradora", "vehiculo", "patente", "direccion",
                           "tipo de siniestro", "comuna / ciudad") and row[1]:
                    rep.meta.setdefault(key, row[1])
    # tablas conocidas
    for page, rows in rep.tables:
        head = [I.norm(c) for c in rows[0]] if rows else []
        if head[:2] == ["n", "alerta"] or head[:2] == ["n°", "alerta"] or (len(head) > 1 and head[1] == "alerta"):
            rep.alerts += [r[1] for r in rows[1:] if len(r) > 1 and r[1]]
        elif head and head[0] == "alerta" and "hallazgo" in head:
            for r in rows[1:]:
                cells = [c for c in r if c]
                if cells:
                    txt = cells[1] if len(cells) > 1 else ""
                    st = STATUS.match(txt)
                    rep.responses.append({"alerta": cells[0], "hallazgo": txt, "estado": st.group(1).capitalize() if st else "", "page": page})
        elif head and head[0] == "hallazgo" and "evidencia" in head:
            for r in rows[1:]:
                cells = [c for c in r if c is not None]
                rep.findings_table.append({"hallazgo": cells[0] if cells else "", "evidencia": cells[1] if len(cells) > 1 else "", "page": page})
        elif len(head) >= 2 and head[1] == "documento":
            rep.documents += [r[1] for r in rows[1:] if len(r) > 1 and r[1]]
    # conclusión
    for title, s in rep.sections.items():
        if "conclusi" in I.norm(title):
            rep.conclusion = s["text"]
            if m := re.search(r"SE RECOMIENDA(?: [A-ZÁÉÍÓÚÑ]{2,})+", s["text"]):
                rep.recommendation = m.group(0).strip()
    # entrevistas
    in_iv, qa = False, None
    for ln in rep.lines:
        m = HEADING.match(ln.text)
        if ln.bold and m:
            in_iv = "entrevista" in I.norm(m.group(2))
            continue
        if not in_iv:
            continue
        if ln.bold and (" — " in ln.text or " - " in ln.text) and not re.match(r"^\d{1,3}\.", ln.text):
            name, _, rol = re.split(r"\s+[—-]\s+", ln.text, maxsplit=1)[0], None, (re.split(r"\s+[—-]\s+", ln.text, maxsplit=1) + [""])[1]
            rep.interviews.append(I.Interview(name.strip(), rol.strip(), index=len(rep.interviews) + 1))
            qa = None
            continue
        if not rep.interviews:
            continue
        iv = rep.interviews[-1]
        if ln.text.lower().startswith("fecha de entrevista"):
            iv.fecha = ln.text.split(":", 1)[1].strip()
            continue
        m = re.match(r"^(\d{1,3})\.\s+(.*)$", ln.text)
        if ln.bold and m:
            qa = I.QA(int(m.group(1)), m.group(2), "", ln.page, True)
            iv.items.append(qa)
        elif qa is not None and ln.bold and not qa.a:
            qa.q += " " + ln.text
        elif qa is not None:
            qa.a = (qa.a + " " + ln.text).strip()


# ---- revisión ----------------------------------------------------------------------------------
TOPIC_IN_REPORT = {
    "usuario_habitual": r"habitual|lo usaba|usaban|solamente yo|quien (lo )?usa",
    "otro_vehiculo": r"se fug|otro vehiculo|huy",
    "uso_app": r"aplicaci|plataforma|carta app",
    "motivo": r"presupuesto|clinica",
    "hora": r"\bhora\b|horario",
    "espera_grua": r"grua",
}
INTERNAL = [
    ("trayecto", r"coherente con (el )?trayecto",
     r"(analisis|calculo) de(l)? trayecto no pudo realizarse|trayecto no pudo realizarse|no pudo realizarse por falta de coordenadas",
     "El informe concluye que el trayecto es coherente ({a}) y también que el análisis de trayecto no pudo realizarse ({b})."),
    ("lesiones", r"no (sufrio|tuvo|presento) (ninguna )?lesion",
     r"(?<!no )(?<!ningun )(sufrio|presento) lesiones|resulto (herido|lesionado)|fue (trasladado|llevado) a (la )?(clinica|hospital|urgencia)",
     "El informe dice que no hubo lesiones ({a}) y también que las hubo o hubo traslado médico ({b})."),
]
_AFFIRM = re.compile(r"^(si|sí|no|correcto|bueno|claro|exacto|ok|de acuerdo|perfecto|ya)\b", re.I)


def page_ev(prefix: str, page: int) -> str:
    return f"{prefix}:{PAGE_BASE + page}"


def audit(rep: ParsedReport, prefix: str) -> list[Finding]:
    out: list[Finding] = []

    def add(rule, sev, cat, title, summary, cites):
        out.append(Finding(rule, sev, title, summary, cites, "", cat))

    responses_text = I.norm(" ".join(r["alerta"] + " " + r["hallazgo"] for r in rep.responses) + " " +
                            " ".join(f["hallazgo"] for f in rep.findings_table) + " " + rep.conclusion)
    for iv in rep.interviews:
        iv.prefix = prefix

    # 1. contradicciones entre entrevistados
    t0 = None
    if fo := rep.meta.get("fecha de ocurrencia"):
        try:
            t0 = datetime.strptime(fo.strip(), "%d/%m/%Y %H:%M").isoformat()
        except ValueError:
            t0 = None
    for f in I.compare(rep.interviews, t0):
        topic = f.rule.replace("contradiction_", "")
        considered = bool(re.search(TOPIC_IN_REPORT.get(topic, "$^"), responses_text))
        if considered:
            f.summary += " El informe aborda este tema en sus respuestas o hallazgos: confirmar que la diferencia quedó explicada."
            f.severity = "baja"
        else:
            f.summary += " El informe no menciona esta diferencia en la respuesta a las alertas ni en los hallazgos."
        f.category = "Contradicciones entre entrevistados"
        out.append(f)

    # 2. contradicciones internas del informe
    by_page = {}
    for ln in rep.lines:
        by_page.setdefault(ln.page, []).append(I.norm(ln.text))
    joined = {p: " ".join(t) for p, t in by_page.items()}
    for key, pos, neg, msg in INTERNAL:
        pa = [p for p, t in joined.items() if re.search(pos, t)]
        pb = [p for p, t in joined.items() if re.search(neg, t)]
        if pa and pb:
            add(f"internal_{key}", "alta", "Coherencia interna del informe", "El informe se contradice",
                msg.format(a="pág. " + ", ".join(map(str, pa)), b="pág. " + ", ".join(map(str, pb))),
                [page_ev(prefix, pa[0]), page_ev(prefix, pb[0])])

    # 3. transcripción
    for iv in rep.interviews:
        for qa in iv.items:
            q = qa.q.strip()
            if "?" not in q and _AFFIRM.match(I.norm(q)) and len(q.split()) <= 12:
                add("transcript_role", "media", "Transcripción", "Posible respuesta marcada como pregunta",
                    f"En la entrevista a {iv.declarante}, el ítem {qa.n} (\"{q}\") parece una respuesta del entrevistado, "
                    f"pero está formateado como pregunta del entrevistador. Revisar la asignación de hablantes.",
                    [iv.ev(qa.n)])
            elif re.search(r"se corta|se cae la llamada|inaudible|no se escucha", I.norm(qa.a)):
                add("transcript_gap", "baja", "Transcripción", "Pregunta sin respuesta registrada",
                    f"En la entrevista a {iv.declarante}, la pregunta {qa.n} quedó sin respuesta ({qa.a.strip()}). "
                    f"Verificar si se repitió más adelante.", [iv.ev(qa.n)])

    # 4. alertas y respuestas
    for i, alert in enumerate(rep.alerts, 1):
        words = {w for w in I.tokens(alert) if len(w) > 3}
        covered = any(len(words & set(I.tokens(r["alerta"] + " " + r["hallazgo"]))) >= max(1, len(words) // 3) for r in rep.responses)
        if words and not covered:
            add("alert_unanswered", "media", "Alertas y conclusión", "Alerta de la compañía sin respuesta visible",
                f"La alerta {i} (\"{alert}\") no parece tener una respuesta en la sección de respuesta a las alertas.",
                [page_ev(prefix, next((ln.page for ln in rep.lines if I.norm(alert)[:25] in I.norm(ln.text)), 1))])
    for r in rep.responses:
        if not r["estado"]:
            add("alert_no_status", "baja", "Alertas y conclusión", "Respuesta sin estado",
                f"La respuesta a \"{r['alerta']}\" no indica un estado (descartado, acreditado, no descartado, indeterminado).",
                [page_ev(prefix, r["page"])])
    rec = I.norm(rep.recommendation or rep.conclusion[:200])
    if "rechaz" in rec:
        states = [I.norm(r["estado"]) for r in rep.responses]
        conc = I.norm(rep.conclusion)
        weak = re.search(r"no (pudo|fue posible|ha sido posible) (ser )?descart|no pudo ser descartad|no permite(n)? (excluir|descartar)", conc)
        proven = re.search(r"se (acredito|comprobo|demostro|constato) que|quedo acreditad[oa] (que|el uso)|confirm(a|o) (el|que) uso", conc)
        if weak and not proven and not any(s.startswith("confirmad") for s in states):
            conc_page = next((ln.page for ln in rep.lines if "RECOMIENDA" in ln.text), rep.pages)
            add("weak_rejection", "media", "Alertas y conclusión", "Rechazo basado en una alerta no descartada",
                "La recomendación de rechazo se funda en que una alerta \"no pudo ser descartada\", sin un hecho que la acredite. "
                "La ley presume que el siniestro está cubierto y la carga de probar una exclusión recae en la aseguradora: "
                "conviene fundar el rechazo en hechos acreditados o revisar el criterio con el área legal.",
                [page_ev(prefix, conc_page)])

    # 5. forma
    for f in rep.findings_table:
        if not re.sub(r"[-\s]", "", f["hallazgo"] + f["evidencia"]):
            add("empty_row", "baja", "Forma", "Fila vacía en la tabla de hallazgos",
                "La tabla de hallazgos tiene una fila sin contenido.", [page_ev(prefix, f["page"])])
            break
    words: dict[str, set[str]] = {}
    for ln in rep.lines:
        for w in re.findall(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{3,}\b", ln.text):
            words.setdefault(I.norm(w), set()).add(w)
    variants = sorted(" / ".join(sorted(v)) for v in words.values() if len(v) > 1)
    if variants:
        add("name_variants", "baja", "Forma", "Palabras escritas de dos formas",
            f"Se encontraron nombres o palabras con y sin tilde: {', '.join(variants[:8])}. Unificar la escritura, "
            f"especialmente en nombres de personas.", [page_ev(prefix, 1)])
    emis = rep.meta.get("fecha de emision")
    try:
        emis_dt = datetime.strptime(emis.strip(), "%d/%m/%Y %H:%M") if emis else None
        occ_dt = datetime.strptime(rep.meta["fecha de ocurrencia"].strip(), "%d/%m/%Y %H:%M") if rep.meta.get("fecha de ocurrencia") else None
    except ValueError:
        emis_dt = occ_dt = None
    for iv in rep.interviews:
        try:
            d = datetime.strptime(iv.fecha.strip(), "%d/%m/%Y %H:%M")
        except ValueError:
            continue
        if (occ_dt and d < occ_dt) or (emis_dt and d > emis_dt):
            add("date_order", "media", "Forma", "Fecha de entrevista fuera de rango",
                f"La entrevista a {iv.declarante} ({iv.fecha}) es anterior al siniestro o posterior a la emisión del informe.",
                [iv.ev(iv.items[0].n) if iv.items else page_ev(prefix, 1)])
    order = {"alta": 0, "media": 1, "baja": 2}
    out.sort(key=lambda f: order[f.severity])
    return out


def topic_matrix(rep) -> list[tuple[str, list[str]]]:
    """Tabla "qué dice cada declarante" por tema. Acepta un informe leído o una lista de entrevistas."""
    ivs = rep.interviews if hasattr(rep, "interviews") else rep
    cls = [I.classify(iv) for iv in ivs]
    rows = []
    for topic, title in I.TOPIC_TITLES.items():
        cells, any_val = [], False
        for iv, c in zip(ivs, cls):
            vals = c.get(topic, [])
            if vals:
                any_val = True
                shown, seen = [], set()
                for v, n, _ in vals:
                    key = repr(v)
                    if key in seen:
                        continue
                    seen.add(key)
                    if topic == "hora":
                        v = I._hhmm(v)
                    elif topic == "espera_grua":
                        v = f"{v[1]} min" if v[0] == "duracion" else f"hasta las {I._hhmm(v[1])}"
                    elif topic == "kilometraje":
                        v = f"{v:,} km".replace(",", ".")
                    shown.append(f"{v} (P{n})")
                cells.append("; ".join(shown))
            else:
                cells.append("—")
        if any_val:
            rows.append((title, cells))
    return rows
