"""Asistente de texto con IA (Groq): transcribir audios, revisar el relato contra el caso, preguntas para la
entrevista y resumen para el jefe.

Es apoyo para el analista, no prueba: lo que diga el modelo se muestra como sugerencia para revisar con la evidencia.
No mira fotos (Groq no tiene modelos de visión en producción) ni detecta ediciones.

Se activa solo si:
  - la clave está en la variable de entorno GROQ_API_KEY (en el servidor: /etc/evidex/evidex.env; nunca en el código);
  - el administrador lo activó en Configuración (los datos salen a Groq, en EE. UU.: requiere autorización de la
    aseguradora; conviene activar «Zero Data Retention» en la consola de Groq).

Se envía lo mínimo: sin RUT, teléfono, correo, dirección ni cuenta bancaria (se tapan también dentro de los textos).
Cada uso queda en la cadena de custodia del caso («Texto enviado a la IA»), con qué tarea y qué modelo.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.groq.com/openai/v1"
MODELO = "llama-3.3-70b-versatile"
MODELO_AUDIO = "whisper-large-v3-turbo"
TIMEOUT = 90
ARCHIVO = "ia_texto.json"
AUDIO_EXT = {".ogg", ".opus", ".mp3", ".m4a", ".wav", ".webm", ".aac"}
MAX_AUDIO = 25 * 1024 * 1024
TAREAS = {"relato": "Revisión del relato", "preguntas": "Preguntas para la entrevista", "resumen": "Resumen del caso",
          "transcripcion": "Transcripción de audio"}
# lo que nunca sale del servidor
NO_ENVIAR = ("rut", "telefono", "email", "direccion", "cuenta_bancaria", "asegurado")

_RUT = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")
_MAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_FONO = re.compile(r"(?:\+?56\s?)?(?:9\s?\d{4}\s?\d{4}|\d{2}\s?\d{3}\s?\d{4})\b")
_CUENTA = re.compile(r"\b\d{8,20}\b")


class IAError(RuntimeError):
    pass


def clave() -> str:
    return (os.environ.get("GROQ_API_KEY") or "").strip()


def activa(cfg: dict) -> bool:
    return bool(clave()) and bool(cfg.get("ia_texto"))


def modelo() -> str:
    return (os.environ.get("GROQ_MODELO") or MODELO).strip()


def tapar(texto: str) -> str:
    """Saca RUT, correos, teléfonos y números largos (cuentas) de un texto antes de enviarlo."""
    t = _RUT.sub("[RUT]", texto or "")
    t = _MAIL.sub("[CORREO]", t)
    t = _FONO.sub("[TELÉFONO]", t)
    return _CUENTA.sub("[NÚMERO]", t)


# ---- llamadas a Groq (se reemplazan en las pruebas) ----------------------------------------------------
def _post(url: str, data: bytes, headers: dict) -> dict:
    # User-Agent propio: el «Python-urllib» que viene por defecto lo bloquea el cortafuegos de Groq (403)
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Authorization": f"Bearer {clave()}", "User-Agent": "Evidex/1.0",
                                          "Accept": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        detalle, cuerpo = "", b""
        try:
            cuerpo = ex.read()
            detalle = json.loads(cuerpo.decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            detalle = re.sub(r"<[^>]+>|\s+", " ", cuerpo[:2000].decode("utf-8", "replace")).strip()[:160]
        if ex.code == 401:
            raise IAError("La clave de Groq no es válida (revise GROQ_API_KEY en el servidor).") from ex
        if ex.code == 403:
            raise IAError("Groq rechazó la conexión (403): revise en la consola de Groq que la clave esté activa y "
                          f"que su organización no tenga restricciones. Detalle: {detalle or 'sin detalle'}") from ex
        if ex.code == 429:
            raise IAError("Groq rechazó por exceso de uso. Espere un minuto e intente de nuevo.") from ex
        raise IAError(f"Groq respondió con un error ({ex.code}). {detalle[:200]}") from ex
    except (urllib.error.URLError, TimeoutError, OSError) as ex:
        raise IAError("No se pudo conectar con Groq. Revise la conexión a internet del servidor.") from ex


def chat_json(sistema: str, usuario: str) -> dict:
    body = json.dumps({"model": modelo(), "temperature": 0.2, "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]})
    out = _post(f"{API}/chat/completions", body.encode("utf-8"), {"Content-Type": "application/json"})
    try:
        return json.loads(out["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, ValueError) as ex:
        raise IAError("La IA respondió en un formato inesperado. Intente de nuevo.") from ex


def transcribir_archivo(path: Path, nombre: str) -> str:
    if Path(path).stat().st_size > MAX_AUDIO:
        raise IAError("El audio pesa más de 25 MB: Groq no lo acepta.")
    b = uuid.uuid4().hex
    parts = []
    for k, v in (("model", MODELO_AUDIO), ("language", "es"), ("response_format", "json"), ("temperature", "0")):
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    safe = re.sub(r"[^\w.\-]", "_", nombre) or "audio.ogg"
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{safe}"\r\n'
                 f"Content-Type: application/octet-stream\r\n\r\n".encode() + Path(path).read_bytes() + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    out = _post(f"{API}/audio/transcriptions", b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={b}"})
    return str(out.get("text") or "").strip()


# ---- lo guardado en el caso ------------------------------------------------------------------------------
def cargar(case) -> dict:
    try:
        d = json.loads((Path(case.root) / ARCHIVO).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _guardar(case, d: dict) -> None:
    from evidex.core.storage import atomic_json
    atomic_json(Path(case.root) / ARCHIVO, d)


def _registrar(case, actor: str, tarea: str, sujeto: str = "") -> dict:
    meta = {"tarea": tarea, "servicio": "Groq", "modelo": MODELO_AUDIO if tarea == "transcripcion" else modelo(),
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "actor": actor}
    case.ledger.append(actor, "llm_used", sujeto or tarea, {k: meta[k] for k in ("tarea", "servicio", "modelo")})
    return meta


# ---- contexto del caso (lo mínimo) ---------------------------------------------------------------------
def _textos_documentos(case, max_docs: int = 6, max_chars: int = 2500) -> list[dict]:
    from evidex.forensics import pdf_versions
    try:
        ocr = json.loads((Path(case.root) / "ocr_documentos.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ocr = {}
    out = []
    for e in case.active_evidence():
        if e["data"].get("note") != "documento" or len(out) >= max_docs:
            continue
        d, name = e["subject"], e["data"].get("original_name", "")
        texto = ocr.get(d) or ""
        if not texto and name.lower().endswith(".pdf"):
            try:
                texto, _ = pdf_versions._text((case.evidence_dir / d).read_bytes(), max_pages=5)
            except Exception:
                texto = ""
        if (texto or "").strip():
            out.append({"documento": name, "texto": tapar(texto)[:max_chars]})
    return out


def contexto(case) -> dict:
    from evidex.claims import service
    from evidex.portal import links
    decl = {k: v for k, v in (service.declaration(case) or {}).items()
            if k not in NO_ENVIAR and v not in (None, "") and not k.startswith("_")}
    for k in ("descripcion", "lugar", "testigos", "taller"):
        if k in decl:
            decl[k] = tapar(str(decl[k]))
    cap = links.load(case) or {}
    relato = ((cap.get("story") or {}).get("text") or "").strip()
    snap = service.snapshot(case) or {}
    alertas = [{"gravedad": f.get("severity"), "alerta": f.get("title"), "detalle": tapar(f.get("summary") or "")[:400]}
               for f in (snap.get("findings") or [])[:25]]
    trans = cargar(case).get("transcripciones") or {}
    audios = [{"audio": t.get("nombre"), "texto": tapar(t.get("texto") or "")[:4000]} for t in trans.values()]
    return {"siniestro": decl, "relato_del_asegurado": tapar(relato)[:6000], "audios_transcritos": audios,
            "documentos": _textos_documentos(case), "alertas_de_evidex": alertas}


SISTEMA = ("Eres un analista experto en fraude de seguros de autos en Chile. Trabajas solo con los datos entregados: "
           "no inventes hechos, no supongas mala fe y no des conclusiones legales. Responde en español de Chile, claro y "
           "breve, y SOLO con un objeto JSON válido con las claves pedidas.")

PROMPTS = {
    "relato": ("Compara lo que cuenta el asegurado (descripción del siniestro, relato del portal y audios transcritos) "
               "con los datos del formulario y con el texto de los documentos. Busca contradicciones concretas: fecha u "
               "hora, lugar, cómo ocurrió, partes del auto dañadas, kilometraje, otros vehículos o personas, taller. "
               "Si no hay contradicciones, deja la lista vacía. JSON: {\"datos_del_relato\": {\"fecha\": , \"hora\": , "
               "\"lugar\": , \"como_ocurrio\": , \"partes_danadas\": [], \"kilometraje\": , \"otros_involucrados\": }, "
               "\"inconsistencias\": [{\"tema\": , \"dice_el_relato\": , \"dice_otra_fuente\": , \"fuente\": , "
               "\"importancia\": \"media\" o \"baja\", \"que_revisar\": }]}"),
    "preguntas": ("Prepara hasta 10 preguntas para la entrevista del asegurado (o de testigos o del taller) que ayuden a "
                  "aclarar las alertas de Evidex y los puntos débiles del relato. Preguntas abiertas, concretas y "
                  "respetuosas, de a una idea. JSON: {\"preguntas\": [{\"para\": \"asegurado\" o \"testigo\" o \"taller\", "
                  "\"pregunta\": , \"por_que\": }]}"),
    "resumen": ("Resume el caso para el jefe de siniestros en 4 a 6 oraciones: qué se declara, qué alertas importan y "
                "qué falta para decidir. JSON: {\"resumen\": , \"puntos_clave\": [], \"falta_para_decidir\": []}"),
}


def ejecutar(case, tarea: str, actor: str) -> dict:
    """Corre una tarea de texto sobre el caso, la guarda y deja la constancia. Devuelve el resultado."""
    if tarea not in PROMPTS:
        raise ValueError(tarea)
    ctx = contexto(case)
    if tarea == "relato" and not (ctx["siniestro"].get("descripcion") or ctx["relato_del_asegurado"] or ctx["audios_transcritos"]):
        raise IAError("El caso todavía no tiene relato: falta la descripción, el relato del portal o un audio transcrito.")
    res = chat_json(SISTEMA, PROMPTS[tarea] + "\n\nDATOS DEL CASO:\n" + json.dumps(ctx, ensure_ascii=False))
    meta = _registrar(case, actor, tarea)
    d = cargar(case)
    d[tarea] = {**meta, "resultado": res}
    _guardar(case, d)
    return d[tarea]


def transcribir(case, digest: str, actor: str) -> dict:
    e = next((x for x in case.active_evidence() if x["subject"] == digest), None)
    if not e or e["data"].get("note") != "audio":
        raise IAError("Ese archivo no es un audio del caso.")
    nombre = e["data"].get("original_name", "audio")
    texto = transcribir_archivo(case.evidence_dir / digest, nombre)
    meta = _registrar(case, actor, "transcripcion", digest)
    d = cargar(case)
    d.setdefault("transcripciones", {})[digest] = {**meta, "nombre": nombre, "texto": texto}
    _guardar(case, d)
    return d["transcripciones"][digest]


def olvidar_archivo(case, digest: str) -> None:
    """Al eliminar definitivamente un audio, se borra también su transcripción."""
    d = cargar(case)
    if digest in (d.get("transcripciones") or {}):
        del d["transcripciones"][digest]
        _guardar(case, d)
