"""Calibra el umbral de un modelo ya entrenado, sin volver a entrenarlo.

El umbral decide desde qué puntaje Evidex da la alerta. Se fija con fotos ORIGINALES que el modelo nunca vio
(partición «validation» de TGIF), para que como máximo el --fpr de ellas dé alarma, y después se mide con la
partición «testing» (otras fotos, también nunca vistas). Todas pasan antes por WhatsApp (1600 px, JPEG 70) y se
analizan en mosaico, igual que en Evidex.

  python training/calibrar.py --modelo modelos/ --validacion datos_val --prueba datos_prueba --fpr 0.015 --salida modelos_cal/

Deja en --salida el mismo .onnx (sin cambios: su sha256 sigue valiendo) y la ficha con el umbral nuevo.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

try:
    _AQUI = Path(__file__).resolve().parent
except NameError:                                # pegado en una celda de notebook: busca training/ al lado
    _AQUI = Path.cwd() / "training"
sys.path.insert(0, str(_AQUI))
from datos import degradar_fijo, preparar, puntuar_mosaico  # noqa: E402

TIPOS = {"orig": "originales (falsas alarmas)", "sd2-sp": "zona editada SD2", "sd2-fr": "regenerada SD2",
         "sdxl-fr": "regenerada SDXL", "ps-sp": "zona editada Photoshop"}


def sesion(onnx: Path):
    import onnxruntime as ort
    opts = ort.SessionOptions()
    return ort.InferenceSession(str(onnx), opts, providers=["CPUExecutionProvider"])


def puntajes(sess, ficha, carpeta: Path) -> np.ndarray:
    correr = lambda t: sess.run(["mapa", "puntaje"], {"imagen": t})      # noqa: E731
    out = []
    for p in sorted(glob.glob(str(carpeta / "**" / "*.png"), recursive=True)):
        img = preparar(degradar_fijo(Image.open(p)), ficha.get("max_lado", 2048))
        out.append(puntuar_mosaico(correr, img, ficha["lado"], ficha.get("paso", ficha["lado"] * 3 // 4))[0])
    return np.array(out)


def umbral_para(orig: np.ndarray, fpr: float) -> float:
    """El menor umbral con el que, como máximo, el `fpr` de las originales da alarma."""
    s = np.sort(orig)
    k = int(np.floor(len(s) * (1 - fpr)))
    return float(s[min(k, len(s) - 1)]) + 1e-7


def tabla(res: dict, u: float) -> dict:
    return {TIPOS[c]: f"{int((v >= u).sum())} de {len(v)} ({100 * (v >= u).mean():.1f} %)"
            for c, v in res.items() if len(v)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modelo", type=Path, required=True, help="carpeta con evidex_ia.onnx y evidex_ia.json")
    ap.add_argument("--validacion", type=Path, required=True, help="TGIF partición validation (orig/ y editadas)")
    ap.add_argument("--prueba", type=Path, help="TGIF partición testing, para medir al final")
    ap.add_argument("--fpr", type=float, default=.015, help="falsas alarmas máximas en originales")
    ap.add_argument("--salida", type=Path, required=True)
    a = ap.parse_args(argv)

    ficha = json.loads((a.modelo / "evidex_ia.json").read_text(encoding="utf-8"))
    onnx = a.modelo / "evidex_ia.onnx"
    if hashlib.sha256(onnx.read_bytes()).hexdigest() != ficha["sha256_onnx"]:
        raise SystemExit("El .onnx no coincide con su ficha (sha256): no se calibra un archivo cambiado.")
    sess = sesion(onnx)
    t = time.time()
    val = {c: puntajes(sess, ficha, a.validacion / c) for c in TIPOS if (a.validacion / c).is_dir()}
    if not len(val.get("orig", [])):
        raise SystemExit("Faltan originales en la validación (carpeta orig/).")
    print(f"Validación puntuada en {time.time() - t:.0f} s: "
          + ", ".join(f"{c} {len(v)}" for c, v in val.items()), flush=True)

    anterior = float(ficha["umbral"])
    opciones = {}
    for f in (.01, .015, .02, .03):
        u = umbral_para(val["orig"], f)
        opciones[f"{f:.1%}"] = {"umbral": u, **tabla(val, u)}
    nuevo = umbral_para(val["orig"], a.fpr)
    print("\nEn validación (fotos nunca vistas), según la meta de falsas alarmas:")
    print(json.dumps(opciones, indent=2, ensure_ascii=False))

    resultado = {"meta_falsas_alarmas": a.fpr, "umbral_anterior": anterior, "umbral_nuevo": nuevo,
                 "originales_para_calibrar": int(len(val["orig"])), "validacion": tabla(val, nuevo),
                 "opciones": opciones}
    if a.prueba:
        prueba = {c: puntajes(sess, ficha, a.prueba / c) for c in TIPOS if (a.prueba / c).is_dir()}
        resultado["prueba_umbral_nuevo"] = tabla(prueba, nuevo)
        resultado["prueba_umbral_anterior"] = tabla(prueba, anterior)
        print("\nPrueba final (partición testing), umbral NUEVO vs ANTERIOR:")
        print(json.dumps({"nuevo": resultado["prueba_umbral_nuevo"],
                          "anterior": resultado["prueba_umbral_anterior"]}, indent=2, ensure_ascii=False))

    a.salida.mkdir(parents=True, exist_ok=True)
    for f in ("evidex_ia.onnx", "evidex_ia.safetensors"):
        if (a.modelo / f).exists() and (a.modelo / f).resolve() != (a.salida / f).resolve():
            shutil.copyfile(a.modelo / f, a.salida / f)
    ficha["umbral"] = nuevo
    ficha["calibracion"] = resultado
    ficha["fpr_objetivo"] = a.fpr
    (a.salida / "evidex_ia.json").write_text(json.dumps(ficha, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nListo: umbral {anterior:.6f} -> {nuevo:.6f}. Ficha nueva en {a.salida / 'evidex_ia.json'}")


if __name__ == "__main__":
    if "ipykernel" in sys.modules:               # se abrió este archivo como notebook por error
        print("Este archivo no es el notebook. En Kaggle importe «evidex_calibrar.ipynb» (File → Import Notebook).")
    else:
        main()
