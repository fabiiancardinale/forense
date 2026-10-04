"""Constantes y utilidades compartidas por las pruebas."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UTF8_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}
ACTUAL = "SIN-2026-0987"      # siniestro sospechoso de la demo
LIMPIO = "SIN-2026-0990"      # siniestro sin alertas de la demo
INV_DEMO = ROOT / "demo" / "investigacion_demo"


def analysis_of(work, numero):
    from evidex.claims import service
    from evidex.core.case import Case
    return service.run_analysis(Case(work / numero), work / "registro.jsonl")


def web_client(tmp_path):
    from evidex.web import create_app
    app = create_app(tmp_path / "casos", {"DEMO_MODE": True, "CSRF_ENABLED": False, "LEGACY_MODULES": True})
    app.config["TESTING"] = True
    return app.test_client()


def textured_image(seed, w=960, h=720):
    """Imagen con textura de foto real (ruido suave y fino), reproducible."""
    import numpy as np
    from PIL import Image
    rng = np.random.RandomState(seed)
    coarse = Image.fromarray(rng.randint(0, 255, (h // 40, w // 40, 3), dtype=np.uint8)).resize(
        (w, h), Image.Resampling.BICUBIC)
    arr = np.asarray(coarse, dtype=np.float32) * 0.6 + rng.randint(60, 190, 3) * 0.4
    arr += rng.normal(0, 6, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def real_pdf() -> bytes:
    """Un PDF de una página válido (los PDF falsos se rechazan al subir)."""
    import io
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (200, 260), "white").save(b, "PDF")
    return b.getvalue()
