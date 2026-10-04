"""Análisis de un siniestro en un proceso aparte, con tiempo y memoria limitados.

El análisis abre las fotos, PDF y chats que mandó el asegurado. Si alguno está hecho para colgar o
reventar un lector, que caiga este proceso desechable y no la web de Evidex para todos los usuarios.

Desde la web se usa `analyze`; la línea de comandos y las pruebas pueden seguir llamando a
`service.analyze_claim` directamente.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

TIMEOUT = 300            # segundos para todo el análisis del caso (incluye reanalizar los vinculados)
MEMORY = 4 * 1024 ** 3   # bytes
EXTERNAL_KEYS = ("google_vision_key", "sightengine_user", "sightengine_secret")


class AnalysisFailed(RuntimeError):
    """El análisis no terminó (tiempo máximo, memoria o archivo que hizo fallar un lector)."""


def analyze(case, registry_path: Path | None, timeout: int = TIMEOUT) -> dict:
    """Corre service.analyze_claim en un proceso aparte y devuelve su resultado."""
    from evidex.core.storage import locked
    payload = json.dumps({"case": str(Path(case.root).resolve()),
                          "registry": str(Path(registry_path).resolve()) if registry_path else None})
    env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    # un análisis a la vez por caso, también entre procesos
    with locked(Path(case.root) / ".analisis.lock", timeout=timeout):
        try:
            proc = subprocess.run([sys.executable, "-m", "evidex.claims.isolated"], input=payload, text=True,
                                  capture_output=True, timeout=timeout, env=env,
                                  cwd=Path(__file__).resolve().parents[2])
        except subprocess.TimeoutExpired as ex:
            raise AnalysisFailed("El análisis superó el tiempo máximo y se detuvo.") from ex
    try:
        out = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as ex:
        raise AnalysisFailed("El análisis se interrumpió (memoria o archivo dañado).") from ex
    if not out.get("ok"):
        raise AnalysisFailed(out.get("error") or "El análisis no pudo completarse.")
    return out["result"]


def _limits(workdir: Path) -> None:
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT, TIMEOUT + 5))
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY, MEMORY))
    except (ImportError, ValueError, OSError):
        pass                       # Windows: rige el tiempo máximo que controla el proceso padre
    # sin red, salvo que se hayan configurado los servicios externos de fotos (Google, Sightengine)
    from evidex.claims.service import load_config
    if not any(load_config(workdir).get(k) for k in EXTERNAL_KEYS):
        def offline(event, args):
            if event in ("socket.connect", "socket.getaddrinfo"):
                raise PermissionError("sin red durante el análisis")
        sys.addaudithook(offline)


def main() -> None:
    payload = json.loads(sys.stdin.read())
    root = Path(payload["case"])
    _limits(root.parent)
    from evidex.claims import service
    from evidex.core.case import Case
    try:
        result = service.analyze_claim(Case(root), Path(payload["registry"]) if payload.get("registry") else None)
        out = {"ok": True, "result": json.loads(json.dumps(result, default=str))}
    except MemoryError:
        out = {"ok": False, "error": "El análisis necesitó demasiada memoria y se detuvo."}
    except Exception as ex:
        out = {"ok": False, "error": f"El análisis no pudo completarse ({type(ex).__name__})."}
    sys.stdout.write(json.dumps(out) + "\n")


if __name__ == "__main__":
    main()
