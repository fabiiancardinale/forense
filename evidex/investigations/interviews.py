"""Entrevistas a declarantes: lectura de transcripciones y detección de contradicciones.

Una investigación de siniestro se apoya en lo que dicen el asegurado, el conductor y los
testigos. Este módulo:
  1. Lee transcripciones numeradas ("12. ¿Pregunta?" + respuesta) o en formato P:/R:.
  2. Extrae lo que dice cada declarante sobre temas clave: quién usa el vehículo, qué pasó con
     el otro vehículo, uso en aplicaciones de transporte, hora del siniestro, motivo del viaje,
     espera de la grúa, kilometraje y RUT.
  3. Compara declarantes entre sí y con los documentos (kilometraje, RUT de terceros).

Cada contradicción cita las preguntas exactas de cada entrevista. Las reglas buscan expresiones
típicas del español de Chile; no entienden todo matiz, así que las alertas son para que el
investigador revise, no conclusiones.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

from evidex.core.detections import Finding

CATEGORY = "Entrevistas"


@dataclass
class QA:
    n: int
    q: str
    a: str
    page: int | None = None
    q_bold: bool = True


@dataclass
class Interview:
    declarante: str
    rol: str = ""
    fecha: str = ""
    items: list[QA] = field(default_factory=list)
    prefix: str = "00000000"   # hash corto de la evidencia de origen
    index: int = 1             # número de entrevista dentro del expediente

    def ev(self, n: int) -> str:
        return f"{self.prefix}:{self.index * 1000 + n}"

    @property
    def short(self) -> str:
        return self.declarante.split()[0] if self.declarante else f"Entrevista {self.index}"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def tokens(s: str) -> list[str]:
    return re.findall(r"[a-z]+", norm(s))


# ---- lectura de transcripciones ----------------------------------------------------------
_NUM = re.compile(r"^\s*(\d{1,3})[.)]\s+(.*)$")
_PR = re.compile(r"^\s*(P|R|Pregunta|Respuesta)\s*[:.-]\s*(.*)$", re.I)


def parse_text(text: str) -> list[QA]:
    """Transcripción en texto: preguntas numeradas seguidas de su respuesta, o bloques P:/R:."""
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    items: list[QA] = []
    if any(_PR.match(ln) for ln in lines):
        n, q, a, mode = 0, [], [], None
        for ln in lines:
            m = _PR.match(ln)
            if m:
                kind = m.group(1)[0].upper()
                if kind == "P":
                    if q:
                        items.append(QA(n, " ".join(q), " ".join(a)))
                    n, q, a, mode = n + 1, [m.group(2)], [], "q"
                else:
                    a, mode = [m.group(2)], "a"
            elif ln.strip() and mode:
                (q if mode == "q" else a).append(ln.strip())
        if q:
            items.append(QA(n, " ".join(q), " ".join(a)))
        return items
    cur, mode = None, None
    for ln in lines:
        m = _NUM.match(ln)
        if m:
            if cur:
                items.append(cur)
            cur, mode = QA(int(m.group(1)), m.group(2).strip(), ""), "q"
            continue
        if cur is None:
            continue
        if not ln.strip():
            if mode == "q":
                mode = "gap"
            continue
        if mode == "q" and not cur.q.rstrip().endswith(("?", ".")):
            cur.q += " " + ln.strip()           # la pregunta sigue en la línea siguiente
        else:
            cur.a = (cur.a + " " + ln.strip()).strip()
            mode = "a"
    if cur:
        items.append(cur)
    return items


# ---- temas ----------------------------------------------------------------------------------
_TIME_WORDS = {"una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
               "nueve": 9, "diez": 10, "once": 11, "doce": 12}


def _clock(text: str) -> int | None:
    """Minutos desde medianoche de la primera hora mencionada ("10:40", "a las 10 de la mañana", "la una de la tarde")."""
    t = norm(text)
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\b", t)
    if m and int(m.group(1)) < 24:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.search(r"\blas? (\d{1,2}|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce)"
                  r"(?: y (media|cuarto))?(?: (?:de la|del) (manana|tarde|noche|mediodia))?", t)
    if not m:
        return None
    h = int(m.group(1)) if m.group(1).isdigit() else _TIME_WORDS[m.group(1)]
    if h > 23:
        return None
    if m.group(3) in ("tarde", "noche") and h < 12:
        h += 12
    mins = 30 if m.group(2) == "media" else 15 if m.group(2) == "cuarto" else 0
    return h * 60 + mins


def _duration(text: str) -> int | None:
    t = norm(text)
    m = re.search(r"(una|un|\d+) hora(?:s)?(?: y (media|\d+ minutos))?(?:,? (?:o )?una hora y media)?", t)
    if m:
        base = 60 if m.group(1) in ("una", "un") else int(m.group(1)) * 60
        if m.group(2) == "media":
            base += 30
        elif m.group(2):
            base += int(re.match(r"\d+", m.group(2)).group())
        # "una hora, una hora y media" -> se toma el máximo mencionado
        if re.search(r"hora y media", t) and base < 90:
            base = 90
        return base
    m = re.search(r"(\d+) minutos", t)
    return int(m.group(1)) if m else None


_KM = re.compile(r"\b(\d{1,3}(?:[.\s]\d{3})+|\d{4,6})\s*(?:km|kilometros|kms)\b")
RUT = re.compile(r"\b(\d{1,2}\.?\d{3}\.?\d{3}-[\dkK])\b")


def km_values(text: str) -> list[int]:
    return [int(re.sub(r"\D", "", m)) for m in _KM.findall(norm(text))]


def fmt_rut(r: str) -> str:
    body, dv = r[:-1], r[-1]
    return f"{int(body):,}".replace(",", ".") + "-" + dv if body.isdigit() else r


def rut_norm(r: str) -> str:
    return re.sub(r"[^0-9K]", "", r.upper())


def classify(iv: Interview) -> dict[str, list[tuple]]:
    """Por tema: lista de (valor, número de pregunta, cita breve)."""
    out: dict[str, list[tuple]] = {}

    def add(topic, value, qa):
        out.setdefault(topic, []).append((value, qa.n, qa.a[:220]))

    for qa in iv.items:
        q, a = norm(qa.q), norm(qa.a)
        both = q + " " + a
        # quién usa habitualmente el vehículo
        if re.search(r"habitualmente|quien (usaba|utilizaba|usa|utiliza|maneja)", q):
            if re.search(r"\b(solamente|solo|unicamente) yo\b|\bes mio\b", a):
                add("usuario_habitual", "solo el conductor", qa)
            elif re.search(r"\b(yo|lo usaba yo|lo usamos)\b.*\b(tambien|y) (mi|el|su) (hijo|hija|padre|madre|esposa|esposo|pareja)"
                           r"|\bambos\b|\blos dos\b|\bcompartid", a):
                add("usuario_habitual", "compartido (asegurado y conductor)", qa)
        # otro vehículo involucrado
        if re.search(r"otro (vehiculo|auto|conductor)|vehiculo que lo encerro|se detuvo|siguio su marcha", both):
            if re.search(r"\b(se fugo|se dio a la fuga|huyo|escapo|arranco|se fue del lugar|se fue sin)\b", a):
                add("otro_vehiculo", "se fugó", qa)
            elif re.search(r"no (tengo|se|puedo|recuerdo|alcance)\b.*(informacion|aclarar|certeza|ver)|no puedo aclarar|no tengo mas informacion", a):
                add("otro_vehiculo", "no lo sabe", qa)
            elif re.search(r"\bse (detuvo|quedo)\b", a):
                add("otro_vehiculo", "se detuvo", qa)
        # uso en aplicaciones de transporte
        if re.search(r"aplicacion(es)? de transporte|uber|cabify|didi|transporte de pasajeros", q) and a:
            if re.search(r"no sabria|no se\b|desconozco|no podria (decir|asegurar)|no tengo conocimiento", a):
                add("uso_app", "no puede descartarlo", qa)
            elif re.search(r"^no\b|jamas|nunca|no,? (lo )?(he|hemos)", a):
                add("uso_app", "lo niega", qa)
        # hora del siniestro
        if re.search(r"a que hora", q) and re.search(r"ocurri|siniestro|accidente|choque", q):
            if (c := _clock(qa.a)) is not None:
                add("hora", c, qa)
        # motivo del viaje (visita médica)
        if re.search(r"clinica|hospital|medic|doctor|kinesiolog|consulta", both):
            if re.search(r"presupuesto", a):
                add("motivo", "pedir un presupuesto", qa)
            elif re.search(r"consulta medica|hora medica|tenia (una )?(hora|consulta|cita)|control|atencion medica", a):
                add("motivo", "consulta médica", qa)
        # espera de la grúa
        if re.search(r"grua", both):
            if (d := _duration(qa.a)) is not None and re.search(r"demor|tiempo|tardo", q):
                add("espera_grua", ("duracion", d), qa)
            elif m := re.search(r"hasta (?:cerca de )?(la una|las \d{1,2}|las (?:dos|tres|cuatro)) de la tarde", a):
                add("espera_grua", ("hasta", _clock(m.group(0).replace("hasta ", "").replace("cerca de ", ""))), qa)
        # kilometraje y RUT
        for km in km_values(qa.a):
            add("kilometraje", km, qa)
        if re.search(r"\brut\b", q):
            for r in RUT.findall(qa.a):
                add("rut", rut_norm(r), qa)
    return out


TOPIC_TITLES = {
    "usuario_habitual": "Quién usa habitualmente el vehículo",
    "otro_vehiculo": "Qué hizo el otro vehículo",
    "uso_app": "Uso en aplicaciones de transporte",
    "hora": "Hora del siniestro",
    "motivo": "Motivo del viaje",
    "espera_grua": "Espera de la grúa",
    "kilometraje": "Kilometraje del vehículo",
}


def _hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def compare(interviews: list[Interview], hora_siniestro: str | None = None) -> list[Finding]:
    """Contradicciones entre declarantes (y con la hora registrada del siniestro)."""
    out: list[Finding] = []
    data = [(iv, classify(iv)) for iv in interviews]
    t0 = None
    if hora_siniestro:
        try:
            d = datetime.fromisoformat(hora_siniestro)
            t0 = d.hour * 60 + d.minute
        except ValueError:
            t0 = None

    def add(rule, sev, topic, summary, cites):
        out.append(Finding(rule, sev, TOPIC_TITLES.get(topic, topic), summary, cites, "", CATEGORY))

    for i, (a, ca) in enumerate(data):
        for b, cb in data[i + 1:]:
            for topic, pairs in (("usuario_habitual", None), ("otro_vehiculo", None), ("uso_app", None), ("motivo", None)):
                va, vb = ca.get(topic, []), cb.get(topic, [])
                if not va or not vb:
                    continue
                sa, sb = {v for v, _, _ in va}, {v for v, _, _ in vb}
                if sa & sb and topic != "motivo":
                    continue
                if topic == "motivo" and sa == sb:
                    continue
                # se citan las respuestas donde los valores difieren
                xa = next((x for x in va if x[0] not in sb), va[0])
                xb = next((x for x in vb if x[0] not in sa), vb[0])
                if topic == "otro_vehiculo" and not ({"se fugó", "no lo sabe"} <= (sa | sb) or {"se fugó", "se detuvo"} <= (sa | sb)):
                    continue
                sev = "media"
                if topic == "uso_app":
                    sev = "baja" if {"lo niega", "no puede descartarlo"} == (sa | sb) else "media"
                summary = (f"{a.declarante} ({a.rol or 'declarante'}) dice: {xa[0]} (pregunta {xa[1]}). "
                           f"{b.declarante} ({b.rol or 'declarante'}) dice: {xb[0]} (pregunta {xb[1]}).")
                add(f"contradiction_{topic}", sev, topic, summary, [a.ev(xa[1]), b.ev(xb[1])])
            # espera de la grúa: duración vs hora de término
            ga, gb = ca.get("espera_grua", []), cb.get("espera_grua", [])
            if ga and gb and t0 is not None:
                def minutes(v):
                    kind, x = v[0]
                    return x if kind == "duracion" else (x - t0 if x is not None else None)
                ma, mb = minutes(ga[0]), minutes(gb[0])
                if ma is not None and mb is not None and abs(ma - mb) >= 45:
                    add("contradiction_espera_grua", "baja", "espera_grua",
                        f"{a.declarante} estima unos {ma} minutos de espera (pregunta {ga[0][1]}); "
                        f"{b.declarante}, unos {mb} minutos (pregunta {gb[0][1]}).", [a.ev(ga[0][1]), b.ev(gb[0][1])])
    if t0 is not None:
        for iv, c in data:
            for v, n, _ in c.get("hora", []):
                if abs(v - t0) >= 30:
                    add("contradiction_hora", "baja", "hora",
                        f"{iv.declarante} sitúa el siniestro a las {_hhmm(v)} (pregunta {n}); la hora registrada es {_hhmm(t0)}.",
                        [iv.ev(n)])
    return out


# ---- cruce con documentos -------------------------------------------------------------------
@dataclass
class DocFacts:
    name: str
    ev: str
    km: list[int] = field(default_factory=list)
    ruts: list[str] = field(default_factory=list)
    date: str | None = None  # fecha del documento si se conoce (ISO)


def doc_facts_from_text(name: str, ev: str, text: str) -> DocFacts:
    t = norm(text)
    dates = re.findall(r"\b(\d{2})[/-](\d{2})[/-](\d{4})\b", t)
    date = None
    if dates:
        d, m, y = dates[0]
        try:
            date = datetime(int(y), int(m), int(d)).date().isoformat()
        except ValueError:
            date = None
    return DocFacts(name, ev, km_values(text), sorted({rut_norm(r) for r in RUT.findall(text)}), date)


def cross_documents(interviews: list[Interview], docs: list[DocFacts], asegurado_rut: str | None = None) -> list[Finding]:
    out: list[Finding] = []
    stated_ruts = set()
    for iv in interviews:
        for v, _, _ in classify(iv).get("rut", []):
            stated_ruts.add(v)
    if asegurado_rut:
        stated_ruts.add(rut_norm(asegurado_rut))
    for iv in interviews:
        for km, n, _ in classify(iv).get("kilometraje", []):
            for d in docs:
                higher = [x for x in d.km if x > km * 1.05]
                if higher:
                    k1, k2 = f"{km:,}".replace(",", "."), f"{higher[0]:,}".replace(",", ".")
                    out.append(Finding("km_mismatch", "alta", "Kilometraje declarado menor que el de un documento",
                                       f"{iv.declarante} declara unos {k1} km en la pregunta {n}, pero {d.name} registra "
                                       f"{k2} km. Si el documento es anterior al siniestro, el odómetro no puede haber bajado.",
                                       [iv.ev(n), d.ev], "", "Documentos"))
    if stated_ruts:
        for d in docs:
            others = [r for r in d.ruts if r not in stated_ruts]
            if others:
                out.append(Finding("third_party_docs", "media", "Documento con RUT de un tercero",
                                   f"{d.name} menciona el RUT {fmt_rut(others[0])}, que no corresponde a ninguno de los "
                                   f"declarantes. Verificar a nombre de quién está el vehículo.", [d.ev], "", "Documentos"))
    return out
