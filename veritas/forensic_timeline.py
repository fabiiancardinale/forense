"""Línea de tiempo forense del siniestro: todos los hechos con fecha, en orden, y lo imposible.

Reúne en una sola secuencia la declaración (hora y lugar del choque, denuncia, póliza), las
fotos (hora de la cámara o del servidor, y GPS), los documentos (creación, modificación y
cada versión recuperada) y los mensajes de los chats. Sobre esa secuencia busca hechos que
no pueden ser ciertos a la vez:

  1. Traslado imposible: dos hechos con ubicación separados por más distancia de la que se
     puede recorrer en el tiempo que hay entre ellos (más de 130 km/h promedio).
  2. Daño fotografiado antes de contratar la póliza.
  3. Presupuesto o factura cuyo texto lleva una fecha anterior al choque.

Los hallazgos de cada fuente (chats, versiones de documentos, fotos) se suman aparte; aquí
solo se agregan los que nacen de cruzar fuentes en el tiempo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .claims import km_between

MAX_KMH = 130
MIN_KM = 5
COST_DOC = re.compile(r"presupuest|cotizaci|factura|boleta|reparaci|repuesto", re.I)
TEXT_DATE = re.compile(r"\bfecha\s*(?:de\s+emisi[oó]n)?\s*:?\s*(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", re.I)

KIND_LABEL = {"siniestro": "Siniestro declarado", "denuncia": "Denuncia", "poliza": "Póliza", "foto": "Foto",
              "documento": "Documento", "version": "Versión de documento", "chat": "Mensaje", "captura": "Captura segura"}


@dataclass
class Event:
    ts: datetime
    kind: str
    title: str
    detail: str = ""
    ev: str | None = None
    place: tuple[float, float] | None = None
    trust: str = ""              # de dónde sale la hora
    flags: list[str] = field(default_factory=list)


def _tokens(name) -> set[str]:
    import unicodedata
    s = unicodedata.normalize("NFD", str(name or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return {t for t in re.findall(r"[a-z]{3,}", s) if t not in ("del", "los", "las")}


def _dt(s) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:19])
    except ValueError:
        try:
            return datetime.fromisoformat(str(s)[:10])
        except ValueError:
            return None


def build(decl: dict, decl_ev: str, photos, docs, chats=()) -> list[Event]:
    ev: list[Event] = []
    t0 = _dt(decl["fecha_siniestro"])
    place = (decl["lat"], decl["lon"]) if decl.get("lat") is not None else None
    ev.append(Event(t0, "siniestro", f"Siniestro en {decl.get('lugar') or 'lugar no indicado'}",
                    (decl.get("descripcion") or "")[:180], decl_ev, place, "declarado por el asegurado"))
    for key, label in (("fecha_denuncia", "Denuncia del siniestro"), ("inicio_poliza", "Inicio de la póliza"),
                       ("cambio_cobertura", "Cambio de cobertura"), ("fin_poliza", "Vencimiento de la póliza")):
        d = _dt(decl.get(key))
        if d and abs(d - t0) < timedelta(days=200):
            ev.append(Event(d, "denuncia" if key == "fecha_denuncia" else "poliza", label, "", decl_ev, None, "declaración"))
    for p in photos:
        m = p.meta
        cap = m.get("secure_capture")
        t = _dt(m.get("taken"))
        trust = "hora del servidor (captura segura)" if cap else "hora de la cámara" if m.get("taken") else ""
        if not t:
            continue
        gps = tuple(m["gps"]) if m.get("gps") else None
        cam = " ".join(filter(None, [m.get("make"), m.get("model")]))
        ev.append(Event(t, "captura" if cap else "foto", f"Foto {p.name}",
                        ", ".join(filter(None, [cam, f"GPS {gps[0]:.4f}, {gps[1]:.4f}" if gps else "sin GPS"])),
                        p.ev, gps, trust))
    for d in docs:
        m = d.meta
        c, mo = _dt(m.get("created")), _dt(m.get("modified"))
        if c:
            ev.append(Event(c, "documento", f"Se crea {d.name}", ", ".join(m.get("tools") or []), d.ev, None,
                            "metadatos del PDF"))
        if mo and c and mo - c > timedelta(minutes=5) and not (m.get("versions") or {}).get("changes"):
            ev.append(Event(mo, "documento", f"Se modifica {d.name}", m.get("producer") or "", d.ev, None,
                            "metadatos del PDF"))
        for ch in (m.get("versions") or {}).get("changes", []):
            t = _dt(ch.get("modified"))
            if t:
                (ao, an), (do, dn) = ch["amounts"], ch["dates"]
                det = "; ".join(filter(None, [f"monto {', '.join(ao)} → {', '.join(an)}" if ao or an else "",
                                              f"fecha {', '.join(do)} → {', '.join(dn)}" if do or dn else ""]))
                ev.append(Event(t, "version", f"Versión {ch['to']} de {d.name}",
                                det or "cambia el texto", d.ev, None, ch.get("producer") or "versión recuperada"))
    from .places import mention
    insured = _tokens(decl.get("asegurado"))
    for prefix, chat, msgs in chats:
        for msg in msgs:
            place = None
            detail = "Mensaje eliminado" if msg.deleted else msg.text[:200]
            hit = None if msg.deleted else mention(msg.text)
            own = bool(insured & _tokens(msg.sender))
            if hit:
                name, lat, lon, how = hit
                detail += f" · dice estar {how} {name}"
                if how == "en":
                    place = (lat, lon)
            e = Event(msg.ts, "chat", f"{msg.sender} ({chat.name})", detail, f"{prefix}:{msg.line}", place,
                      "hora del chat exportado")
            e.insured = own
            e.place_name = hit[0] if hit else None
            ev.append(e)
    ev.sort(key=lambda e: e.ts)
    return ev


def impossibilities(decl: dict, decl_ev: str, events: list[Event], docs) -> list:
    from .detections import Finding
    out = []

    def add(rule, sev, title, summary, cite, ts):
        out.append(Finding(rule, sev, title, summary, cite, ts.isoformat(), "Línea de tiempo"))

    # 1. traslado imposible entre hechos con ubicación (fotos con GPS y el lugar declarado)
    # el chat cuenta solo si quien escribe es el asegurado (otro participante puede estar en otra ciudad)
    located = [e for e in events if e.place and (e.kind in ("siniestro", "foto", "captura")
                                                 or (e.kind == "chat" and getattr(e, "insured", False)))]
    flagged = set()
    for a, b in zip(located, located[1:]):
        km = km_between(a.place, b.place)
        hours = (b.ts - a.ts).total_seconds() / 3600
        if km < MIN_KM:
            continue
        speed = km / hours if hours > 0 else float("inf")
        if speed > MAX_KMH and (a.ev, b.ev) not in flagged:
            flagged.add((a.ev, b.ev))
            mins = int(hours * 60)
            for e in (a, b):
                e.flags.append("traslado imposible")

            def desc(e):
                if e.kind == "chat":
                    return f"El mensaje de {e.title.split(' (')[0]} que dice estar en {e.place_name}"
                return e.title
            add("impossible_travel", "alta", "Traslado imposible entre dos hechos",
                f"{desc(a)} ({a.ts:%d-%m-%Y %H:%M}) y {desc(b)[0].lower() + desc(b)[1:] if b.kind == 'chat' else desc(b)} ({b.ts:%d-%m-%Y %H:%M}) están a {km:.0f} km de distancia "
                f"con {mins} minuto(s) entre ellos: habría que viajar a {min(speed, 9999):.0f} km/h. Al menos una de las "
                "dos horas o ubicaciones no es real.", [x for x in (a.ev, b.ev) if x], b.ts)

    # 2. daño fotografiado antes de la póliza
    start = _dt(decl.get("inicio_poliza"))
    if start:
        early = [e for e in events if e.kind in ("foto", "captura") and e.ts < start]
        if early:
            for e in early:
                e.flags.append("antes de la póliza")
            add("photo_before_policy", "alta", "Daño fotografiado antes de contratar la póliza",
                f"{len(early)} foto(s) del daño tienen fecha anterior al inicio de la póliza ({start:%d-%m-%Y}); la primera, "
                f"{early[0].title}, del {early[0].ts:%d-%m-%Y %H:%M}. El daño podría ser anterior a la cobertura.",
                [e.ev for e in early[:4] if e.ev] + [decl_ev], early[0].ts)

    # 3. presupuesto o factura con fecha impresa anterior al choque
    t0 = _dt(decl["fecha_siniestro"])
    for d in docs:
        if not COST_DOC.search(d.name + " " + (d.meta.get("text") or "")[:300]):
            continue
        for m in TEXT_DATE.finditer(d.meta.get("text") or ""):
            dd, mm, yy = (int(x) for x in m.groups())
            yy += 2000 if yy < 100 else 0
            try:
                printed = datetime(yy, mm, dd)
            except ValueError:
                continue
            if printed.date() < t0.date():
                add("doc_dated_before", "alta", f"Documento con fecha anterior al choque ({d.name})",
                    f"El documento {d.name} dice “{m.group(0).strip()}”, {(t0.date() - printed.date()).days} día(s) antes del siniestro "
                    f"declarado ({t0:%d-%m-%Y}). Un presupuesto o factura de la reparación no puede ser anterior al daño.",
                    [d.ev, decl_ev], printed)
                for e in events:
                    if e.ev == d.ev:
                        e.flags.append("fecha anterior al choque")
                break
    return out
