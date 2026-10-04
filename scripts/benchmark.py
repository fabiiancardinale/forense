"""Banco de pruebas: mide cuántas fotos editadas detecta Evidex y cuántas originales marca por error.

Uso:
  python scripts/benchmark.py --originales carpeta_orig --editadas carpeta_edit [--whatsapp] [--n 100] [--salida res.jsonl]

--whatsapp simula el envío por WhatsApp antes de analizar: lado mayor 1600 px, JPEG calidad 70, sin metadatos.
Así se mide el caso difícil (la foto llega sin la «firma» de la app que la editó).

Datos sugeridos (licencia que permite uso comercial; revise la licencia de cada conjunto):
  TGIF / TGIF2 (CC BY 4.0 / CC BY-SA 4.0) — https://github.com/IDLabMedia/tgif-dataset
Los resultados son métricas de triaje: «suspicious» cuenta como positivo. No certifican autenticidad.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff"}


def whatsapp_like(src: Path, dst: Path, max_side: int = 1600, quality: int = 70) -> Path:
    """Lo que hace WhatsApp con una foto «normal»: reduce, recomprime y borra metadatos."""
    from PIL import Image
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality, optimize=True)     # sin exif= ni icc_profile=: se pierden
    dst.write_bytes(buf.getvalue())
    return dst


def files(folder: Path, n: int) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in IMAGES)[:n]


def triage(res: dict, hits: list[str], ignore: set[str]) -> str:
    """Lo que ve el analista. Sin un detector de IA externo el informe dice «No concluyente» aunque no haya
    alertas; para medir, eso cuenta como «sin indicios». Las reglas en `ignore` no cuentan como alerta."""
    if [h for h in hits if h not in ignore]:
        return "alteration_detected" if any(f.get("confirmed_change") for f in res["findings"]
                                            if f["rule"] not in ignore) else "suspicious"
    missing = [d for d in res["detectors"] if d["status"] in ("error", "not_run", "partial")
               and d.get("required", True) and d["name"] != "IA global"]
    return "inconclusive" if missing else "no_indications"


def run(originals: Path, edited: Path, n: int, whatsapp: bool, out: Path | None,
        ignore: set[str] = frozenset()) -> dict:
    from evidex.inspection.pipeline import analyze
    from evaluate_predictions import evaluate
    rows, rules = [], {"edited": Counter(), "original": Counter()}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        k = 0
        for label, folder in (("original", originals), ("edited", edited)):
            for src in files(folder, n):
                k += 1
                # nombre neutro: el nombre del conjunto («..._sd2_0.png») delataría la respuesta
                name = f"IMG-{k:05d}-WA.jpg" if whatsapp else f"IMG_{k:05d}{src.suffix.lower()}"
                path = whatsapp_like(src, tmp / name) if whatsapp else src
                t = time.monotonic()
                try:
                    res = analyze(path, name, tmp)
                    hits = [f["rule"] for f in res["findings"]]
                    verdict = triage(res, hits, ignore)
                except Exception as ex:                       # un archivo que no se pudo leer es una abstención
                    verdict, hits = "failed", [type(ex).__name__]
                rules[label].update(hits)
                rows.append({"id": f"{label}/{src.relative_to(folder)}", "label": label, "verdict": verdict,
                             "rules": hits, "seconds": round(time.monotonic() - t, 2)})
    if out:
        out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return {**evaluate(rows), "whatsapp": whatsapp, "reglas_ignoradas": sorted(ignore),
            "reglas_en_editadas": dict(rules["edited"].most_common(10)),
            "reglas_en_originales": dict(rules["original"].most_common(10))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--originales", type=Path, required=True)
    ap.add_argument("--editadas", type=Path, required=True)
    ap.add_argument("--n", type=int, default=100, help="máximo de fotos por carpeta")
    ap.add_argument("--whatsapp", action="store_true", help="simular el envío por WhatsApp antes de analizar")
    ap.add_argument("--ignorar", default="", help="reglas separadas por coma que no cuentan como alerta "
                    "(p. ej. ai_dimensions si el conjunto usa imágenes de 512 px)")
    ap.add_argument("--salida", type=Path, help="guardar el detalle por foto (JSONL)")
    a = ap.parse_args(argv)
    print(json.dumps(run(a.originales, a.editadas, a.n, a.whatsapp, a.salida,
                         {r.strip() for r in a.ignorar.split(",") if r.strip()}), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
