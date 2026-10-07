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

FORMATOS = (1, 2)        # 1 = foto entera achicada al lado del modelo; 2 = mosaico a tamaño real
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
    if card.get("formato") not in FORMATOS:
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


def _hot_box(prob: np.ndarray, thr: float, w: int, h: int, floor: float = .5):
    """Caja (en píxeles de la foto) de la zona más sospechosa, o None."""
    m = prob >= max(thr, floor)
    if m.sum() < 4:
        return None
    from evidex.forensics.image_content import _largest_blob
    ys, xs = np.nonzero(_largest_blob(m))                  # la zona más grande, no todas las sueltas
    sx, sy = w / prob.shape[1], h / prob.shape[0]
    return [int(xs.min() * sx), int(ys.min() * sy), int((xs.max() + 1) * sx), int((ys.max() + 1) * sy)]


# ---- mosaico (igual que training/datos.py: tests/test_learned_model.py revisa que den lo mismo) ----------
def _positions(n: int, side: int, step: int) -> list[int]:
    if n <= side:
        return [0]
    return list(range(0, n - side, step)) + [n - side]


def _prepare(img: Image.Image, max_side: int) -> Image.Image:
    img = img.convert("RGB")
    if max(img.size) > max_side:
        f = max_side / max(img.size)
        img = img.resize((max(1, round(img.width * f)), max(1, round(img.height * f))), Image.LANCZOS)
    return img


def _normalize(img: Image.Image) -> np.ndarray:
    return (np.asarray(img, dtype=np.float32) / 255.0 - MEAN) / STD


def _mosaic_score(run, img: Image.Image, side: int, step: int, batch: int = 8):
    """(puntaje = el del pedazo más sospechoso, mapa de la foto a 1/esc, esc)."""
    w, h = img.size
    W, H = max(w, side), max(h, side)
    x = np.empty((H, W, 3), np.float32)
    x[:] = (0 - MEAN) / STD                                   # relleno negro, como al entrenar
    x[:h, :w] = _normalize(img)
    pos = [(xx, yy) for yy in _positions(H, side, step) for xx in _positions(W, side, step)]
    tiles = np.stack([x[yy:yy + side, xx:xx + side].transpose(2, 0, 1) for xx, yy in pos]).astype(np.float32)
    maps, scores = [], []
    for i in range(0, len(tiles), batch):
        m, s = run(tiles[i:i + batch])
        maps.append(np.asarray(m))
        scores.append(np.asarray(s).reshape(-1))
    maps, scores = np.concatenate(maps)[:, 0], np.concatenate(scores)
    esc = side // maps.shape[-1]
    acc = np.zeros((H // esc + 1, W // esc + 1), np.float32)
    cnt = np.zeros_like(acc)
    for (xx, yy), m in zip(pos, maps):
        acc[yy // esc:yy // esc + m.shape[0], xx // esc:xx // esc + m.shape[1]] += m
        cnt[yy // esc:yy // esc + m.shape[0], xx // esc:xx // esc + m.shape[1]] += 1
    return float(scores.max()), (acc / np.maximum(cnt, 1))[:max(1, h // esc), :max(1, w // esc)], esc


def check(path) -> dict:
    """{"score", "threshold", "flag", "region": {"bbox", "area"}, "model"} o {} si no hay modelo."""
    sess, card = _load()
    if sess is None:
        return {}
    side = int(card.get("lado", 512))
    thr = float(card["umbral"])
    with Image.open(path) as img:
        orig_w, orig_h = img.size
        if card.get("modo") == "mosaico":
            img = _prepare(img, int(card.get("max_lado", 2048)))
            n = sess.get_inputs()[0].shape[0]                    # lote fijo del modelo, o variable
            score, prob, _ = _mosaic_score(lambda t: sess.run(["mapa", "puntaje"], {"imagen": t}),
                                           img, side, int(card.get("paso", side * 3 // 4)),
                                           batch=n if isinstance(n, int) and n > 0 else 8)
        else:                                                     # modelos de formato 1: foto entera achicada
            x = _normalize(img.convert("RGB").resize((side, side), Image.BILINEAR))
            m, s = sess.run(["mapa", "puntaje"], {"imagen": x.transpose(2, 0, 1)[None].astype(np.float32)})
            prob, score = m[0, 0], float(s[0])
    out = {"score": round(score, 4), "threshold": round(thr, 4), "flag": score >= thr, "model": card["_id"]}
    box = _hot_box(prob, thr, orig_w, orig_h) if out["flag"] else None
    if box:
        out["region"] = {"bbox": box, "area": round(float((prob >= max(thr, .5)).mean()), 4)}
    # la zona más sospechosa aunque no llegue al umbral: se muestra solo si otra prueba ya confirmó que la
    # foto se editó con IA (firma del teléfono, marca visible, copia de una foto marcada), para saber dónde mirar
    peak = float(prob.max()) if prob.size else 0.0
    best = _hot_box(prob, peak * .9, orig_w, orig_h, floor=0) if peak > 0 else None
    if best:
        out["best"] = {"bbox": best, "peak": round(peak, 4)}
    return out
