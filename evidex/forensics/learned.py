"""Detector aprendido (opcional): zonas posiblemente editadas con IA, aunque la foto pasó por WhatsApp.

Se activa solo si existe un modelo en la carpeta `modelos/` (o la que indique EVIDEX_MODELO):
  evidex_ia.onnx   el modelo (lo genera training/entrenar.py)
  evidex_ia.json   su ficha: umbral, conjuntos de entrenamiento y sus licencias, sha256 del .onnx
Sin modelo, Evidex funciona igual que antes. Se usa onnxruntime (ya viene con el OCR): no hace falta torch
ni GPU en el servidor, y no se carga ningún pickle (un pickle puede ejecutar código al abrirse).

El modelo NO se carga si:
  - la ficha falta, no calza el formato o el sha256 no coincide (archivo cambiado o dañado);
  - algún conjunto de entrenamiento tiene una licencia no comercial o desconocida.
El resultado es un indicio para revisar («revisar esta zona»), nunca una prueba.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

import numpy as np
from PIL import Image

FORMATO = 1
NOMBRE = "evidex_ia"
LICENCIAS_BLOQUEADAS = ("nc", "non-commercial", "noncommercial", "no comercial", "research only", "desconocida")
DEFAULT_DIR = Path(__file__).resolve().parents[2] / "modelos"
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)

_lock = threading.Lock()
_cache: dict = {}


def model_dir() -> Path:
    return Path(os.environ.get("EVIDEX_MODELO") or DEFAULT_DIR)


def _license_ok(lic: str) -> bool:
    l = (lic or "desconocida").lower()
    return not any(b in l for b in LICENCIAS_BLOQUEADAS)


def _load():
    """(sesión, ficha) o (None, motivo). Se recarga si cambia el archivo."""
    d = model_dir()
    onnx_p, card_p = d / f"{NOMBRE}.onnx", d / f"{NOMBRE}.json"
    try:
        key = (str(onnx_p), onnx_p.stat().st_mtime_ns, card_p.stat().st_mtime_ns)
    except OSError:
        return None, "sin modelo"
    with _lock:
        if _cache.get("key") == key:
            return _cache["value"]
        value = _open(onnx_p, card_p)
        _cache.update(key=key, value=value)
        return value


def _open(onnx_p: Path, card_p: Path):
    try:
        card = json.loads(card_p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "ficha del modelo ilegible"
    if card.get("formato") != FORMATO:
        return None, f"formato de modelo {card.get('formato')} no soportado"
    data = onnx_p.read_bytes()
    if hashlib.sha256(data).hexdigest() != card.get("sha256_onnx"):
        return None, "el modelo no coincide con su ficha (sha256)"
    bad = [c.get("nombre") for c in card.get("conjuntos") or [{}] if not _license_ok(c.get("licencia"))]
    if bad or not card.get("conjuntos"):
        return None, f"licencia no comercial o desconocida en: {bad or 'sin conjuntos declarados'}"
    try:
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        sess = ort.InferenceSession(data, opts, providers=["CPUExecutionProvider"])
    except Exception as ex:                          # onnxruntime ausente o modelo inválido
        return None, f"no se pudo abrir el modelo ({type(ex).__name__})"
    card["_id"] = card["sha256_onnx"][:12]
    return sess, card


def status() -> dict:
    sess, card = _load()
    if sess is None:
        return {"available": False, "reason": card}
    return {"available": True, "id": card["_id"], "name": card.get("nombre"), "threshold": card["umbral"],
            "validation": card.get("validacion")}


def available() -> bool:
    return _load()[0] is not None


def model_id() -> str | None:
    sess, card = _load()
    return card["_id"] if sess is not None else None


def _hot_box(prob: np.ndarray, thr: float, w: int, h: int):
    """Caja (en píxeles de la foto) de la zona más sospechosa, o None."""
    m = prob >= max(thr, .5)
    if m.sum() < 4:
        return None
    ys, xs = np.nonzero(m)
    sx, sy = w / prob.shape[1], h / prob.shape[0]
    return [int(xs.min() * sx), int(ys.min() * sy), int((xs.max() + 1) * sx), int((ys.max() + 1) * sy)]


def check(path) -> dict:
    """{"score", "threshold", "flag", "region": {"bbox", "area"}, "model"} o {} si no hay modelo."""
    sess, card = _load()
    if sess is None:
        return {}
    side = int(card.get("lado", 512))
    with Image.open(path) as img:
        img = img.convert("RGB")
        w, h = img.size
        x = np.asarray(img.resize((side, side), Image.BILINEAR), dtype=np.float32) / 255.0
    x = ((x - MEAN) / STD).transpose(2, 0, 1)[None].astype(np.float32)
    prob, score = sess.run(["mapa", "puntaje"], {"imagen": x})
    prob, score, thr = prob[0, 0], float(score[0]), float(card["umbral"])
    out = {"score": round(score, 4), "threshold": round(thr, 4), "flag": score >= thr, "model": card["_id"]}
    box = _hot_box(prob, thr, w, h) if out["flag"] else None
    if box:
        out["region"] = {"bbox": box, "area": round(float((prob >= max(thr, .5)).mean()), 4)}
    return out
