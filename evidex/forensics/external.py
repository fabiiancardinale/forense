"""Servicios externos opcionales para las fotos: detector de IA y búsqueda inversa en internet.

  - Detector de imágenes generadas o editadas con IA: Sightengine (modelo "genai").
  - Búsqueda inversa: Google Cloud Vision (detección web), que devuelve páginas e imágenes
    publicadas en internet que coinciden con la foto.

Ambos son de pago por uso y se activan solo si se configuran sus claves en Configuración.
Importante: la foto se envía al proveedor. En producción esto requiere la autorización de la
aseguradora y revisar la política de datos personales del proveedor.

Los resultados se guardan por hash de la foto (servicios_externos.json en el caso) para no
pagar dos veces por la misma consulta.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

SIGHTENGINE_URL = "https://api.sightengine.com/1.0/check.json"
VISION_URL = "https://vision.googleapis.com/v1/images:annotate"
TIMEOUT = 25


def configured(cfg: dict) -> dict:
    return {"ai": bool(cfg.get("sightengine_user") and cfg.get("sightengine_secret")),
            "web": bool(cfg.get("google_vision_key"))}


def _post(url: str, data: bytes, headers: dict) -> dict:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _multipart(fields: dict, file_field: str, filename: str, content: bytes) -> tuple[bytes, str]:
    b = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
                 f"Content-Type: application/octet-stream\r\n\r\n".encode() + content + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={b}"


def ai_check(path: Path, cfg: dict) -> dict:
    """{'score': 0..1} o {'error': texto}."""
    body, ctype = _multipart({"models": "genai", "api_user": cfg["sightengine_user"], "api_secret": cfg["sightengine_secret"]},
                             "media", Path(path).name, Path(path).read_bytes())
    try:
        r = _post(SIGHTENGINE_URL, body, {"Content-Type": ctype})
    except (urllib.error.URLError, TimeoutError, ValueError) as ex:
        return {"error": f"sin respuesta del servicio ({type(ex).__name__})"}
    if r.get("status") != "success":
        return {"error": (r.get("error") or {}).get("message", "respuesta inválida")}
    t = r.get("type") or {}
    gens = t.get("ai_generators") or {}
    top = max(gens.items(), key=lambda kv: kv[1]) if gens else None
    return {"score": float(t.get("ai_generated", 0)), "generator": top[0] if top and top[1] > 0.5 else None}


def web_search(path: Path, cfg: dict) -> dict:
    """{'full': [urls], 'pages': [(url, título)]} o {'error': texto}."""
    payload = {"requests": [{"image": {"content": base64.b64encode(Path(path).read_bytes()).decode()},
                             "features": [{"type": "WEB_DETECTION", "maxResults": 10}]}]}
    url = VISION_URL + "?" + urllib.parse.urlencode({"key": cfg["google_vision_key"]})
    try:
        r = _post(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    except (urllib.error.URLError, TimeoutError, ValueError) as ex:
        return {"error": f"sin respuesta del servicio ({type(ex).__name__})"}
    resp = (r.get("responses") or [{}])[0]
    if "error" in resp:
        return {"error": resp["error"].get("message", "error del servicio")}
    w = resp.get("webDetection") or {}
    return {"full": [x["url"] for x in w.get("fullMatchingImages", []) if x.get("url")][:10],
            "pages": [(p.get("url"), p.get("pageTitle", "")) for p in w.get("pagesWithMatchingImages", []) if p.get("url")][:10]}


def run(case, photos, cfg: dict) -> dict:
    """Consulta los servicios configurados para cada foto que aún no tenga resultado."""
    on = configured(cfg)
    if not any(on.values()):
        return {}
    cache_path = case.root / "servicios_externos.json"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    changed = False
    for p in photos:
        if p.meta.get("error"):
            continue
        entry = cache.setdefault(p.digest, {})
        path = case.evidence_dir / p.digest
        if on["ai"] and ("ai" not in entry or "error" in entry["ai"]):
            entry["ai"] = ai_check(path, cfg); changed = True
        if on["web"] and ("web" not in entry or "error" in entry["web"]):
            entry["web"] = web_search(path, cfg); changed = True
    if changed:
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return cache


def findings(photos, results: dict) -> list:
    from evidex.core.detections import Finding
    out = []
    for p in photos:
        r = results.get(p.digest) or {}
        ai = r.get("ai") or {}
        if "score" in ai and ai["score"] >= 0.5:
            sev = "alta" if ai["score"] >= 0.8 else "media"
            gen = f", probablemente con {ai['generator']}" if ai.get("generator") else ""
            out.append(Finding("ai_detected", sev, f"Detector de IA: imagen generada o editada ({p.name})",
                               f"El detector externo estima un {ai['score'] * 100:.0f}% de probabilidad de que la foto {p.name} "
                               f"haya sido generada o editada con inteligencia artificial{gen}.", [p.ev], p.ts, "Fotos"))
        web = r.get("web") or {}
        if web.get("full") or web.get("pages"):
            where = web["pages"][0][0] if web.get("pages") else web["full"][0]
            n = len(web.get("pages") or web.get("full"))
            out.append(Finding("found_online", "alta" if web.get("full") else "media",
                               f"La foto aparece publicada en internet ({p.name})",
                               f"La búsqueda inversa encontró la foto {p.name} en {n} sitio(s) de internet, por ejemplo {where}. "
                               "Una foto propia del choque no debería estar publicada antes del reclamo.", [p.ev], p.ts, "Fotos"))
    return out
