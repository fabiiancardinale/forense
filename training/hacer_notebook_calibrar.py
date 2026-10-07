"""Genera training/evidex_calibrar.ipynb: ajusta el umbral de un modelo ya entrenado (sin GPU, menos de 1 hora).

  python training/hacer_notebook_calibrar.py
"""
import json
from pathlib import Path

from hacer_notebook import AQUI, code, md

ARCHIVOS = ("datos.py", "descargar_tgif.py", "calibrar.py")

CELDAS = [md("""
# Evidex: calibrar el umbral del modelo

No entrena de nuevo: toma el modelo ya entrenado y ajusta **desde qué puntaje se da la alerta**, usando fotos
originales que el modelo nunca vio (partición *validation* de TGIF). Después mide con la partición *testing*.

Antes de empezar:
1. Suba el `evidex_modelo.zip` de la vuelta 3 como *Dataset* (Create → New Dataset, por ejemplo «evidex-modelo-v3»)
   y agréguelo con **+ Add Input**.
2. **Settings → Internet:** activado. No necesita GPU (Accelerator: None).

Después: **Save Version → Save & Run All (Commit)**. Tarda menos de 1 hora. Al final descargue
`evidex_modelo_calibrado.zip` desde **Output** y copie los 3 archivos a `veritas\\modelos\\`.
"""),
    code("""
# 1. Configuración
import os
FPR = float(os.environ.get("EVX_FPR", 0.015))          # meta: como máximo 1,5 % de originales con alarma
N_ORIG_VAL = int(os.environ.get("EVX_N_ORIG_VAL", 1200))   # originales para calibrar (más = umbral más estable)
N_EDIT_VAL = int(os.environ.get("EVX_N_EDIT_VAL", 200))    # editadas por tipo, para ver cuánto se detecta
N_PRUEBA = int(os.environ.get("EVX_N_PRUEBA", 300))
BASE = "/kaggle/temp" if os.path.isdir("/kaggle") else "."
os.makedirs(BASE, exist_ok=True)
SALIDA = "/kaggle/working/modelos" if os.path.isdir("/kaggle") else "modelos_calibrado"
"""),
    code("""
# 2. Preparar
import subprocess, sys, glob, shutil
def sh(cmd):
    print("$", cmd, flush=True)
    if subprocess.run(cmd, shell=True).returncode:
        raise SystemExit(f"Falló: {cmd}")
sh(f"{sys.executable} -m pip install -q onnxruntime")
from pathlib import Path
Path("training").mkdir(exist_ok=True)
ARCHIVOS = __ARCHIVOS__
for nombre, contenido in ARCHIVOS.items():
    Path("training", nombre).write_text(contenido, encoding="utf-8")
modelo = glob.glob("/kaggle/input/**/evidex_ia.onnx", recursive=True) if os.path.isdir("/kaggle") else \\
         glob.glob(os.environ.get("EVX_MODELO", "modelos") + "/evidex_ia.onnx")
if not modelo:
    raise SystemExit("No encontré evidex_ia.onnx: agregue el modelo de la vuelta 3 con «+ Add Input».")
MODELO = os.path.dirname(modelo[0])
print("Modelo:", MODELO)
"""),
    code("""
# 3. Bajar fotos que el modelo nunca vio: «validation» para calibrar y «testing» para medir
VAL, PRUEBA = f"{BASE}/tgif_val", f"{BASE}/tgif_prueba"
sh(f"{sys.executable} training/descargar_tgif.py --destino {VAL} --n {N_ORIG_VAL} --particion validation --carpetas orig")
sh(f"{sys.executable} training/descargar_tgif.py --destino {VAL} --n {N_EDIT_VAL} --particion validation --carpetas sd2-sp,sd2-fr,sdxl-fr,ps-sp")
sh(f"{sys.executable} training/descargar_tgif.py --destino {PRUEBA} --n {N_PRUEBA} --particion testing --carpetas orig,sd2-sp,sd2-fr,sdxl-fr,ps-sp")
"""),
    code("""
# 4. Calibrar y medir (imprime las opciones de 1 %, 1,5 %, 2 % y 3 % y el resultado final)
sh(f"{sys.executable} training/calibrar.py --modelo {MODELO} --validacion {VAL} --prueba {PRUEBA} --fpr {FPR} --salida {SALIDA}")
"""),
    code("""
# 5. Empaquetar para descargar (Output → evidex_modelo_calibrado.zip)
shutil.make_archive(os.path.join(os.path.dirname(SALIDA) or ".", "evidex_modelo_calibrado"), "zip", SALIDA)
print("Listo:", sorted(os.listdir(SALIDA)))
"""),
]


def main():
    archivos = {n: (AQUI / n).read_text(encoding="utf-8") for n in ARCHIVOS}
    celdas = json.loads(json.dumps(CELDAS))
    for c in celdas:
        src = "".join(c["source"])
        if "__ARCHIVOS__" in src:
            c["source"] = src.replace("__ARCHIVOS__", json.dumps(archivos, ensure_ascii=False, indent=1)).splitlines(True)
    nb = {"cells": celdas, "nbformat": 4, "nbformat_minor": 5,
          "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                       "language_info": {"name": "python"},
                       "kaggle": {"accelerator": "none", "isInternetEnabled": True}}}
    destino = AQUI / "evidex_calibrar.ipynb"
    destino.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print(destino)


if __name__ == "__main__":
    main()
