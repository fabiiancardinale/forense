"""Portal del asegurado: un enlace donde la persona entrega todo lo del siniestro, sin WhatsApp.

Al registrar el caso, el analista genera un enlace y se lo envía al asegurado (por WhatsApp, SMS
o correo: lo que viaja es solo el enlace). En el enlace, el asegurado:
  1. toma las fotos del vehículo con la cámara en vivo (captura segura, ver abajo);
  2. sube los documentos que se le pidieron (licencia, padrón, constancia, presupuesto...);
  3. puede subir fotos que ya tenía, como archivo original, con su fecha y lugar intactos;
  4. puede escribir su relato con sus propias palabras;
  5. presiona "Enviar todo".
Cada archivo entra a la cadena de custodia en el instante en que llega, con la hora del servidor.

Captura segura de las fotos del vehículo:

Por qué es más seguro que recibir fotos por WhatsApp o correo:
  - La página no permite elegir fotos de la galería ni pantallazos: solo la cámara en vivo.
  - La fecha y hora las pone este servidor al recibir la foto, no el teléfono.
  - La ubicación se toma del GPS del teléfono en el momento, con su autorización.
  - El enlace tiene un código de un solo uso que el asegurado escribe en un papel y muestra en
    la foto de la patente: una foto preparada de antes no puede tenerlo.
  - Cada foto entra a la cadena de custodia con su hash en el instante en que llega.

Límites: no impide que alguien fotografíe una pantalla o un daño provocado; el código y el
análisis de imagen ayudan a detectar lo primero. En producción debe publicarse con HTTPS y un
dominio de la aseguradora; para la demo, Veritas lo sirve en la red local con un certificado propio.
"""
from __future__ import annotations

import io
import json
import secrets
import socket
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

SHOTS = [
    ("frontal", "Vehículo completo de frente"),
    ("trasera", "Vehículo completo por atrás"),
    ("lateral", "Costado donde está el daño, completo"),
    ("dano_cerca", "El daño de cerca"),
    ("patente", "La patente, con el papel que tiene el código escrito"),
]
DOC_TYPES = {
    "licencia": "Licencia de conducir de quien manejaba",
    "carnet": "Cédula de identidad del asegurado (por ambos lados)",
    "padron": "Padrón o certificado de inscripción del vehículo",
    "constancia": "Constancia o parte de Carabineros",
    "presupuesto": "Presupuesto del taller",
    "boletas": "Boletas o facturas de gastos (grúa, repuestos)",
    "otro": "Otro documento que quiera agregar",
}
DEFAULT_DOCS = ["licencia", "padron", "constancia", "presupuesto"]
FILE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".pdf"}
MAX_PHOTOS = 20
MAX_FILES = 40
MAX_BYTES = 12_000_000
MAX_FILE_BYTES = 25_000_000
LINK_HOURS = 24 * 7


def _path(case) -> Path:
    return case.root / "captura.json"


def load(case) -> dict | None:
    try:
        return json.loads(_path(case).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save(case, data: dict) -> None:
    _path(case).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def create_link(case, actor: str = "liquidador", docs: list[str] | None = None, hours: int = LINK_HOURS,
                custom: list[str] | None = None) -> dict:
    """Crea (o renueva) el enlace del caso. Lo ya recibido con un enlace anterior se conserva.
    `custom`: documentos pedidos que no están en la lista, escritos por el analista."""
    old = load(case) or {}
    docs = [d for d in (docs if docs is not None else old.get("doc_ids", DEFAULT_DOCS)) if d in DOC_TYPES and d != "otro"]
    custom = [c.strip()[:120] for c in (custom if custom is not None else old.get("custom", [])) if c and c.strip()][:8]
    entries = [{"id": d, "label": DOC_TYPES[d]} for d in docs]
    entries += [{"id": f"pedido{i}", "label": c} for i, c in enumerate(custom, 1)]
    entries.append({"id": "otro", "label": "Otros documentos que quiera agregar", "optional": True})
    data = {
        "token": secrets.token_urlsafe(24),
        "code": f"{secrets.randbelow(9000) + 1000}",
        "created": datetime.now().isoformat(timespec="seconds"),
        "expires": (datetime.now() + timedelta(hours=hours)).isoformat(timespec="seconds"),
        "shots": [{"id": k, "label": v} for k, v in SHOTS],
        "doc_ids": docs,
        "custom": custom,
        "docs": entries,
        "received": old.get("received", []),
        "files": old.get("files", []),
        "story": old.get("story"),
        "finished": None,
        "opened": None,
        "by": actor,
    }
    _save(case, data)
    # en la custodia queda que se creó el enlace y su código, no el token completo
    case.ledger.append(actor, "capture_link_created", data["token"][:6] + "…",
                       {"code": data["code"], "expires": data["expires"]})
    return data


def find(workdir: Path, token: str):
    from veritas.core.case import Case
    if not token or len(token) < 20:
        return None, None
    for d in Path(workdir).iterdir() if Path(workdir).is_dir() else []:
        f = d / "captura.json"
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if secrets.compare_digest(data.get("token", ""), token):
                return Case(d), data
    return None, None


def status(data: dict) -> str | None:
    """Motivo por el que el enlace ya no sirve, o None si está activo."""
    if data.get("finished"):
        return "Ya envió todo para este siniestro. Si necesita agregar algo, pida un enlace nuevo a su ejecutivo."
    if datetime.now() > datetime.fromisoformat(data["expires"]):
        return "El enlace venció. Pida uno nuevo a su ejecutivo."
    return None


def progress(data: dict, excluded=()) -> dict:
    """Avance del portal: dos pasos, fotos y documentos. No cuenta los archivos quitados
    (por el asegurado, o por el analista: excluded = hashes quitados del análisis)."""
    shots_done = {r["shot"] for r in data.get("received", [])}
    files = [f for f in data.get("files", []) if not f.get("removed") and f.get("sha256") not in excluded]
    photos = [f for f in files if f["kind"] in ("photo", "extra")]
    docs = [f for f in files if f["kind"] == "doc"]
    photos_ok = bool(photos) or bool(shots_done)
    docs_ok = bool(docs)
    done = int(photos_ok) + int(docs_ok)
    return {"shots_done": shots_done, "photos": photos, "docs": docs, "photos_ok": photos_ok, "docs_ok": docs_ok,
            "requested": [d["label"] for d in data.get("docs", []) if not d.get("optional")],
            "story": bool(data.get("story")), "finished": data.get("finished"), "done": done, "total": 2,
            "pct": round(50 * done)}


def _now_pair():
    return datetime.now().isoformat(timespec="seconds"), datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _safe_name(name: str) -> str:
    import re
    stem = re.sub(r"[^\w.\-]+", "_", Path(name or "archivo").name)[:80].strip("._") or "archivo"
    return stem


def _slug(title: str) -> str:
    import re
    import unicodedata
    t = unicodedata.normalize("NFD", title.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:50] or "archivo"


def remove_file(case, data: dict, sha256: str) -> dict:
    """El asegurado quita un archivo que subió por error, antes de enviar todo.
    El archivo no se borra (cadena de custodia): queda registrado y fuera del análisis."""
    if why := status(data):
        raise ValueError(why)
    rec = next((f for f in data.get("files", []) if f.get("sha256") == sha256 and not f.get("removed")), None)
    if not rec:
        raise ValueError("Ese archivo no está en la lista.")
    others = [f for f in data.get("files", []) if f is not rec and f.get("sha256") == sha256 and not f.get("removed")]
    if not others:
        case.exclude_evidence(sha256, "asegurado (portal)", "El asegurado lo quitó: lo subió por error")
    rec["removed"] = _now_pair()[0]
    _save(case, data)
    return rec


def receive_file(case, data: dict, filename: str, blob: bytes, kind: str, title: str = "", user_agent: str = "",
                 last_modified: str = "") -> dict:
    """Foto o documento que sube el asegurado, con el título que él le da.
    Se guarda el archivo original tal cual, con sus metadatos (fecha, cámara, GPS)."""
    if why := status(data):
        raise ValueError(why)
    kind = {"extra": "photo", "foto": "photo", "documento": "doc"}.get(kind, kind)
    if kind not in ("doc", "photo"):
        raise ValueError("Tipo de archivo desconocido.")
    title = " ".join((title or "").split())[:80]
    if len(title) < 3:
        raise ValueError("Escriba un título para el archivo (por ejemplo: Parachoques trasero, Licencia de conducir).")
    if len(data.get("files", [])) >= MAX_FILES:
        raise ValueError("Ya se recibió el máximo de archivos para este enlace.")
    if not blob:
        raise ValueError("El archivo está vacío.")
    if len(blob) > MAX_FILE_BYTES:
        raise ValueError("El archivo es demasiado grande (máximo 25 MB).")
    ext = Path(filename or "").suffix.lower()
    if ext not in FILE_EXT:
        raise ValueError("Solo se aceptan fotos (JPG, PNG, HEIC) o documentos PDF.")
    if ext == ".pdf":
        if not blob[:1024].lstrip().startswith(b"%PDF"):
            raise ValueError("El archivo no es un PDF válido.")
    elif ext in (".heic", ".heif"):
        if b"ftyp" not in blob[:32]:
            raise ValueError("El archivo no es una foto válida.")
    else:
        try:
            with Image.open(io.BytesIO(blob)) as img:
                img.verify()
        except Exception:
            raise ValueError("El archivo no es una foto válida.")
    if kind == "photo" and ext == ".pdf":
        kind = "doc"                      # un PDF siempre es un documento
    if kind == "photo" and sum(1 for f in data.get("files", []) if f["kind"] in ("photo", "extra")) >= MAX_PHOTOS:
        raise ValueError("Ya se recibió el máximo de fotos para este enlace (20).")
    local, utc = _now_pair()
    rec = {"kind": kind, "title": title, "original_name": (filename or "")[:120], "server_time": local, "server_utc": utc,
           "device": user_agent[:160]}
    # fecha del archivo en el teléfono (la informa el navegador): si es muy posterior a la de la foto,
    # el archivo se editó o se volvió a guardar
    if last_modified.isdigit() and 10 <= len(last_modified) <= 14:
        rec["last_modified"] = int(last_modified)
    n = len(data.get("files", [])) + 1
    prefix = "doc" if kind == "doc" else "foto"
    with tempfile.TemporaryDirectory() as td:
        # el nombre guardado lleva el título que dio el asegurado; el nombre original queda en la custodia
        p = Path(td) / f"{prefix}_{n:02d}_{_slug(title)}{ext}"
        p.write_bytes(blob)
        note = "documento" if kind == "doc" else "foto"
        digest = case.add_evidence(p, analyst="asegurado (portal)", note=note, extra={"portal": rec})
    rec.update({"sha256": digest, "name": p.name})
    data.setdefault("files", []).append(rec)
    _save(case, data)
    return rec


def save_story(case, data: dict, text: str) -> None:
    if why := status(data):
        raise ValueError(why)
    text = (text or "").strip()
    if len(text) < 10:
        raise ValueError("Escriba al menos una frase.")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "relato_del_asegurado.txt"
        p.write_text(text[:8000], encoding="utf-8")
        case.add_evidence(p, analyst="asegurado (portal)", note="relato", extra={"portal": {"kind": "relato", "server_time": _now_pair()[0]}})
    data["story"] = {"text": text[:8000], "server_time": _now_pair()[0]}
    _save(case, data)


def finish(case, data: dict) -> None:
    if why := status(data):
        raise ValueError(why)
    p = progress(data)
    data["finished"] = _now_pair()[0]
    _save(case, data)
    case.ledger.append("asegurado (portal)", "portal_finished", data["token"][:6] + "…",
                       {"fotos": len(p["photos"]) + len(p["shots_done"]), "documentos": len(p["docs"]),
                        "relato": p["story"]})


def mark_opened(case, data: dict) -> None:
    if not data.get("opened"):
        data["opened"] = _now_pair()[0]
        _save(case, data)


def share_message(numero: str, nombre: str, url: str, expires: str, empresa: str = "") -> str:
    vence = datetime.fromisoformat(expires).strftime("%d-%m-%Y")
    saludo = f"Hola {nombre.split()[0]}" if nombre and not nombre.lower().startswith("asegurado") else "Hola"
    quien = f" de {empresa}" if empresa else ""
    return (f"{saludo}, le escribimos{quien} por su siniestro {numero}. Para continuar necesitamos fotos del vehículo "
            f"(puede subir las que tomó ese día desde la galería de su teléfono) y algunos documentos. Súbalos en este "
            f"enlace, no por WhatsApp, así se conservan la fecha y el lugar originales de cada foto:\n\n{url}\n\n"
            f"El enlace vence el {vence}.")


def wa_number(phone: str) -> str:
    import re
    d = re.sub(r"\D", "", phone or "")
    if len(d) == 9 and d.startswith("9"):
        d = "56" + d
    return d if len(d) >= 11 else ""


def _f(v):
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def receive(case, data: dict, blob: bytes, form: dict, user_agent: str = "") -> dict:
    """Valida y registra una foto recibida. Devuelve el registro de la captura."""
    if why := status(data):
        raise ValueError(why)
    if len(data["received"]) >= MAX_PHOTOS:
        raise ValueError("Ya se recibió el máximo de fotos para este enlace.")
    if len(blob) > MAX_BYTES:
        raise ValueError("La foto es demasiado grande.")
    try:
        with Image.open(io.BytesIO(blob)) as img:
            img.verify()
        with Image.open(io.BytesIO(blob)) as img:
            fmt, size = img.format, img.size
    except Exception:
        raise ValueError("El archivo recibido no es una imagen válida.")
    if fmt != "JPEG":
        raise ValueError("Formato no permitido.")
    shot = form.get("shot", "")
    if shot not in {s["id"] for s in data["shots"]}:
        raise ValueError("Toma desconocida.")

    now_local = datetime.now()
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    client = form.get("client_time") or ""
    skew = None
    try:
        skew = round((datetime.fromisoformat(client.replace("Z", "")) - now_utc).total_seconds())
    except ValueError:
        pass
    rec = {
        "shot": shot,
        "server_time": now_local.isoformat(timespec="seconds"),
        "server_utc": now_utc.isoformat(timespec="seconds"),
        "lat": _f(form.get("lat")), "lon": _f(form.get("lon")), "accuracy_m": _f(form.get("acc")),
        "gps_error": (form.get("gps_error") or "")[:80] or None,
        "clock_skew_s": skew,
        "size": list(size),
        "device": user_agent[:160],
        "code": data["code"],
    }
    n = len(data["received"]) + 1
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / f"captura_{n:02d}_{shot}.jpg"
        p.write_bytes(blob)
        digest = case.add_evidence(p, analyst="asegurado (captura segura)", note="foto", extra={"capture": rec})
    rec["sha256"] = digest
    data["received"].append(rec)
    _save(case, data)
    return rec


def lan_ip() -> str:
    """IP del equipo en la red local (sin enviar datos: solo consulta la ruta)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def qr_png(url: str) -> bytes | None:
    try:
        import qrcode  # opcional: pip install qrcode
    except ImportError:
        return None
    img = qrcode.make(url, box_size=6, border=2)
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


# ---- hallazgos propios de una foto de captura segura ---------------------------------------
def findings_for(photo, decl: dict, cite: list[str]):
    from veritas.core.detections import Finding
    c = photo.meta.get("secure_capture") or {}
    out = []
    if c.get("lat") is None:
        out.append(Finding("capture_no_gps", "media", f"Captura sin ubicación ({photo.name})",
                           f"La foto {photo.name} se tomó con el enlace seguro, pero el asegurado no autorizó la "
                           f"ubicación{' (' + c['gps_error'] + ')' if c.get('gps_error') else ''}. No se puede confirmar "
                           "que estaba en el lugar.", cite, photo.ts))
    elif (c.get("accuracy_m") or 0) > 1000:
        out.append(Finding("capture_gps_imprecise", "baja", f"Ubicación poco precisa ({photo.name})",
                           f"La ubicación de {photo.name} tiene un margen de {c['accuracy_m']:.0f} m.", cite, photo.ts))
    if c.get("clock_skew_s") is not None and abs(c["clock_skew_s"]) > 600:
        mins = abs(c["clock_skew_s"]) // 60
        out.append(Finding("capture_clock_skew", "baja", f"Reloj del teléfono desfasado ({photo.name})",
                           f"El reloj del teléfono estaba {mins} minutos {'adelantado' if c['clock_skew_s'] > 0 else 'atrasado'} "
                           "respecto del servidor. No afecta la fecha registrada (la pone el servidor), pero puede "
                           "indicar un teléfono con la hora cambiada a mano.", cite, photo.ts))
    return out
