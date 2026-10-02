"""Chats de WhatsApp exportados ("Exportar chat", .txt o .zip) como evidencia del siniestro.

Qué revisa, contra la declaración:
  1. Mensajes que hablan del choque, del seguro o del presupuesto ANTES de la hora declarada
     del siniestro: el hecho se conversó antes de ocurrir.
  2. Frases de libreto: "dile que", "acuérdate que", "no digas", "hay que decir"...
  3. Mensajes eliminados cerca del siniestro.
  4. Teléfonos, patentes y RUT mencionados en el chat que aparecen en otros siniestros
     (vínculo con la red) o que no corresponden al vehículo declarado.

Cada mensaje es un evento citable de la línea de tiempo (hash del archivo + línea).
Límites: el archivo exportado lo entrega el propio asegurado y se puede editar como texto;
la exportación no incluye mensajes borrados antes de exportar. Sirve para orientar la
investigación y debe confirmarse con la persona o con el teléfono.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from evidex.forensics.chile import norm_plate, plates_in, ruts_in

CHAT_EXT = {".txt", ".zip"}
# Android: "20/09/26, 18:41 - Nombre: texto" · iOS: "[20/09/26, 18:41:12] Nombre: texto"
LINE = re.compile(
    r"^‎?\[?(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4}),?\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*"
    r"([ap]\.?\s?m\.?)?\]?\s*(?:-\s*)?([^:]{1,60}?):\s(.*)$", re.I)
DELETED = re.compile(r"(se eliminó este mensaje|eliminaste este mensaje|este mensaje fue eliminado|message was deleted)", re.I)
MEDIA = re.compile(r"(<multimedia omitido>|<media omitted>|imagen omitida|audio omitido|video omitido|\.(jpg|opus|mp4) \(archivo adjunto\))", re.I)
EVENT_WORDS = re.compile(r"\b(choc\w*|colisi\w*|siniestro\w*|accidente\w*|seguro\w*|liquidador\w*|presupuest\w*|"
                         r"denuncia\w*|grúa|grua|taller\w*|deducible|parte policial|carabiner\w*|chocad\w*)\b", re.I)
SCRIPT = re.compile(r"\b(dile que|dí que|di que|digamos que|acuérdate que|acuerdate que|no digas|no les digas|"
                    r"hay que decir|la versión es|la version es|tenemos que decir|ponte de acuerdo|"
                    r"borra (el|los|este|esto)|que no se note)\b", re.I)
PHONE = re.compile(r"(?:\+?56\s?)?9[\s.]?\d{4}[\s.]?\d{4}")


@dataclass
class Message:
    line: int
    ts: datetime
    sender: str
    text: str
    deleted: bool = False
    media: bool = False


@dataclass
class Chat:
    name: str
    messages: list[Message] = field(default_factory=list)

    @property
    def participants(self) -> list[str]:
        seen = []
        for m in self.messages:
            if m.sender not in seen:
                seen.append(m.sender)
        return seen


def _q(text: str, n: int) -> str:
    """Cita corta sin puntos internos, para que el resumen no la corte en dos oraciones."""
    t = re.sub(r"[.!?]+(\s|$)", r",\1", text.replace("\n", " ")).strip(" ,")
    return t[:n] + ("…" if len(t) > n else "")


def _year(y: str) -> int:
    y = int(y)
    return y + 2000 if y < 100 else y


def parse_text(text: str, name: str = "chat.txt") -> Chat:
    chat = Chat(name)
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.replace(" ", " ").replace("\xa0", " ").rstrip()
        m = LINE.match(line)
        if not m:
            if chat.messages and line.strip():             # continuación de un mensaje de varias líneas
                chat.messages[-1].text += "\n" + line
            continue
        d, mo, y, h, mi, s, ampm, sender, body = m.groups()
        h = int(h)
        if ampm:
            pm = ampm.lower().startswith("p")
            h = h % 12 + (12 if pm else 0)
        try:
            ts = datetime(_year(y), int(mo), int(d), h, int(mi), int(s or 0))
        except ValueError:
            continue
        sender = sender.strip().lstrip("‎")
        chat.messages.append(Message(n, ts, sender, body.strip(), bool(DELETED.search(body)), bool(MEDIA.search(body))))
    return chat


def read(path: Path, name: str | None = None) -> Chat | None:
    """Lee un .txt exportado o el _chat.txt dentro de un .zip. None si no parece un chat."""
    raw = Path(path).read_bytes()
    name = name or Path(path).name
    if raw[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                txt = next((n for n in z.namelist() if n.lower().endswith(".txt")), None)
                if not txt:
                    return None
                raw = z.read(txt)
        except zipfile.BadZipFile:
            return None
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    chat = parse_text(text, name)
    return chat if len(chat.messages) >= 2 else None


def looks_like_chat(path: Path) -> bool:
    try:
        return read(path) is not None
    except Exception:
        return False


# ---- análisis ----------------------------------------------------------------------------------
def analyze(decl: dict, decl_ev: str, chats: list[tuple[str, Chat]], registry: list[dict]) -> list:
    """chats: lista de (prefijo de evidencia, Chat). Devuelve hallazgos de la categoría Comunicaciones."""
    from evidex.core.detections import Finding
    out = []
    t0 = datetime.fromisoformat(decl["fecha_siniestro"])
    plate = norm_plate(decl.get("patente"))
    others = [r for r in registry if r.get("type") == "claim" and r.get("claim") != decl.get("numero")]
    phone_owner = {}
    for r in others:
        p = re.sub(r"\D", "", r.get("e_telefono") or (r.get("display") or {}).get("telefono") or "")[-8:]
        if p:
            phone_owner.setdefault(p, r["claim"])

    def add(rule, sev, title, summary, cite, ts):
        out.append(Finding(rule, sev, title, summary, cite, ts.isoformat(), "Comunicaciones"))

    def ev(prefix, m):
        return f"{prefix}:{m.line}"

    for prefix, chat in chats:
        early = [m for m in chat.messages if m.ts < t0 - timedelta(minutes=10) and not m.deleted
                 and EVENT_WORDS.search(m.text) and t0 - m.ts < timedelta(days=30)]
        if early:
            first = early[0]
            add("chat_before_event", "alta", f"Se habló del choque antes de que ocurriera ({chat.name})",
                f"{len(early)} mensaje(s) de {chat.name} mencionan el choque, el seguro o el presupuesto antes de la hora "
                f"declarada del siniestro ({t0:%d-%m-%Y %H:%M}). El primero, de {first.sender} el "
                f"{first.ts:%d-%m-%Y %H:%M}: “{_q(first.text, 140)}”.",
                [ev(prefix, m) for m in early[:4]] + [decl_ev], first.ts)

        script = [m for m in chat.messages if SCRIPT.search(m.text)]
        if script:
            m0 = script[0]
            add("chat_script", "alta", f"Mensajes que acuerdan qué decir ({chat.name})",
                f"{len(script)} mensaje(s) parecen acordar una versión de los hechos. Por ejemplo, {m0.sender} el "
                f"{m0.ts:%d-%m-%Y %H:%M}: “{_q(m0.text, 160)}”.", [ev(prefix, m) for m in script[:4]], m0.ts)

        deleted = [m for m in chat.messages if m.deleted and abs(m.ts - t0) <= timedelta(hours=48)]
        if deleted:
            add("chat_deleted", "media", f"Mensajes eliminados cerca del siniestro ({chat.name})",
                f"{len(deleted)} mensaje(s) fueron eliminados en las 48 horas alrededor del siniestro "
                f"(el primero por {deleted[0].sender}, {deleted[0].ts:%d-%m-%Y %H:%M}).",
                [ev(prefix, m) for m in deleted[:4]], deleted[0].ts)

        for m in chat.messages:
            for ph in PHONE.findall(m.text):
                key = re.sub(r"\D", "", ph)[-8:]
                if key in phone_owner:
                    add("chat_phone_link", "alta", f"El chat menciona un teléfono de otro siniestro ({chat.name})",
                        f"{m.sender} menciona el teléfono {ph.strip()} el {m.ts:%d-%m-%Y %H:%M}, el mismo registrado en el "
                        f"siniestro {phone_owner[key]} de otro asegurado.", [ev(prefix, m)], m.ts)
                    phone_owner.pop(key)
        if plate:
            seen = []
            for m in chat.messages:
                for p in plates_in(m.text):
                    if p != plate and p not in seen:
                        seen.append(p)
                        add("chat_other_plate", "baja", f"El chat menciona otra patente ({chat.name})",
                            f"{m.sender} menciona la patente {p} el {m.ts:%d-%m-%Y %H:%M}; el vehículo declarado es "
                            f"{decl.get('patente')}. Puede ser el otro vehículo involucrado: conviene confirmarlo.",
                            [ev(prefix, m)], m.ts)
        bad_ruts = [(r, m) for m in chat.messages for r, ok in ruts_in(m.text) if not ok]
        if bad_ruts:
            r, m = bad_ruts[0]
            add("chat_rut_invalid", "baja", f"RUT inválido mencionado en el chat ({chat.name})",
                f"{m.sender} menciona el RUT {r}, que no tiene un dígito verificador válido.", [ev(prefix, m)], m.ts)
    return out


def relevant(chat: Chat, t0: datetime, limit: int = 40) -> list[Message]:
    """Mensajes para la línea de tiempo: los que hablan del hecho, los de libreto, los borrados
    y los cercanos al siniestro (±6 h)."""
    from evidex.forensics.places import mention
    keep = [m for m in chat.messages if EVENT_WORDS.search(m.text) or SCRIPT.search(m.text) or m.deleted
            or abs(m.ts - t0) <= timedelta(hours=6) or (abs(m.ts - t0) <= timedelta(days=2) and mention(m.text))]
    return keep[:limit]
