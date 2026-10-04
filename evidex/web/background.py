"""Análisis de siniestros en segundo plano: la página del caso abre al instante.

Antes, abrir un siniestro con evidencia nueva (o después de actualizar Evidex con pruebas nuevas)
dejaba la página esperando hasta que terminara el análisis completo. Ahora el caso abre con su último
análisis, el análisis nuevo corre aparte (en su propio proceso, ver claims/isolated.py) y la página se
actualiza sola al terminar.

El estado de cada caso se guarda en `analisis_estado.json`, en la carpeta del caso:
  {"state": "running" | "done" | "failed", "started": ..., "finished": ..., "error": ..., "result": ...}
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

STATE_FILE = "analisis_estado.json"
MAX_PARALLEL = 2                 # análisis a la vez: cada uno usa un núcleo y hasta 4 GB

_lock = threading.Lock()
_running: set[str] = set()
_slots = threading.BoundedSemaphore(MAX_PARALLEL)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def status(case) -> dict:
    """Estado del último análisis en segundo plano del caso ({} si nunca hubo)."""
    try:
        st = json.loads((Path(case.root) / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if st.get("state") == "running" and not is_running(case):
        # quedó a medias porque Evidex se cerró o reinició: se muestra como fallido para poder reintentar
        st = {**st, "state": "failed", "error": "El análisis se interrumpió porque Evidex se cerró o reinició."}
    return st


def is_running(case) -> bool:
    return str(Path(case.root).resolve()) in _running


def _write(case, data: dict) -> None:
    p = Path(case.root) / STATE_FILE
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(p)


def start(case, run, on_done=None, info: dict | None = None) -> bool:
    """Lanza `run()` (el análisis) en segundo plano si el caso no se está analizando ya.
    `on_done(result)` se llama al terminar bien. Devuelve False si ya había uno en curso."""
    key = str(Path(case.root).resolve())
    with _lock:
        if key in _running:
            return False
        _running.add(key)
    info = dict(info or {})
    _write(case, {"state": "running", "started": _now(), **info})

    def work():
        try:
            with _slots:
                result = run()
            if on_done:
                on_done(result)
            _write(case, {"state": "done", "finished": _now(), **info,
                          "result": {k: result.get(k) for k in ("findings", "recommendation", "reanalyzed")}
                          if isinstance(result, dict) else None})
        except Exception as ex:                                   # el error se muestra en la página del caso
            _write(case, {"state": "failed", "finished": _now(), **info, "error": str(ex) or type(ex).__name__})
        finally:
            with _lock:
                _running.discard(key)
    threading.Thread(target=work, name=f"analisis-{Path(case.root).name}", daemon=True).start()
    return True


def wait(case, timeout: float = 60) -> None:
    """Espera a que termine el análisis del caso (para pruebas y la línea de comandos)."""
    import time
    end = time.monotonic() + timeout
    while is_running(case) and time.monotonic() < end:
        time.sleep(0.05)
