"""Genera training/evidex_generar_autos.ipynb: fabrica fotos de autos editadas con IA en Kaggle («Run all»).

  python training/hacer_notebook_autos.py
"""
import json

from hacer_notebook import AQUI, code, md

ARCHIVOS = ("generar_autos.py",)

CELDAS = [md("""
# Evidex: fabricar fotos de autos editadas con IA

No existe un conjunto público de autos editados con IA, así que lo fabricamos:
- **Fotos:** «Car parts and car damages» de Humans in the Loop (1.812 fotos de autos, **CC0**: uso comercial libre).
- **Editores** (licencias que permiten uso comercial): SDXL inpainting (OpenRAIL++-M), Kandinsky 2.2 (Apache 2.0)
  y LaMa (Apache 2.0, el «borrador de objetos» de las galerías).
- **Ediciones:** borrar un daño real, agregar un daño a una parte sana, rehacer un foco, espejo, patente o llanta.
  Cada una con su máscara exacta (blanco = lo que cambió).

Antes de empezar, en **Settings**: **Accelerator: GPU T4 x2** e **Internet: activado**.
Opcional: **+ Add Input** → buscar «car parts and car damages» (de humansintheloop); si no, se descarga solo.

Después: **Save Version → Save & Run All (Commit)**. Tarda unas 4 a 6 horas. Al final queda
`evidex_autos_ia.zip` en **Output**: agréguelo como Input en el notebook de entrenamiento (vuelta 4).
"""),
    code("""
# 1. Configuración
import os
MAX_HORAS = float(os.environ.get("EVX_MAX_HORAS", 7.5))   # para antes y deja lo que alcanzó (Kaggle corta a las 12 h)
LIMITE = int(os.environ.get("EVX_LIMITE", 0))              # 0 = todas las fotos; un número = prueba rápida
SEMILLA = int(os.environ.get("EVX_SEMILLA", 0))
BASE = "/kaggle/temp" if os.path.isdir("/kaggle") else "."
SALIDA = f"{BASE}/autos_ia"
"""),
    code("""
# 2. Preparar
import subprocess, sys, glob, shutil, time
from pathlib import Path
def sh(cmd):
    print("$", cmd, flush=True)
    if subprocess.run(cmd, shell=True).returncode:
        raise SystemExit(f"Falló: {cmd}")
sh(f"{sys.executable} -m pip install -q diffusers transformers accelerate")
Path("training").mkdir(exist_ok=True)
ARCHIVOS = __ARCHIVOS__
for nombre, contenido in ARCHIVOS.items():
    Path("training", nombre).write_text(contenido, encoding="utf-8")
import torch
N_GPU = torch.cuda.device_count()
LAMA = f"{BASE}/big-lama.pt"            # LaMa se baja una vez aquí (las dos GPU lo comparten)
if not os.path.exists(LAMA):
    sh(f"curl -sL -o {LAMA} https://github.com/enesmsahin/simple-lama-inpainting/releases/download/v0.1.0/big-lama.pt")
print("GPU:", [torch.cuda.get_device_name(i) for i in range(N_GPU)] or "NO HAY GPU (active el acelerador en Settings)")
"""),
    code("""
# 3. Las fotos de autos (CC0): del Input si se agregó, si no se descargan
hitl = sorted({str(Path(p).parents[2]) for p in glob.glob("/kaggle/input/**/ann/*.json", recursive=True)})
if hitl:
    HITL = os.path.commonpath(hitl)
else:
    HITL = f"{BASE}/hitl"
    if not glob.glob(f"{HITL}/**/ann/*.json", recursive=True):
        sh(f"curl -sL -o {BASE}/hitl.zip https://www.kaggle.com/api/v1/datasets/download/humansintheloop/car-parts-and-car-damages")
        sh(f"cd {BASE} && mkdir -p hitl && cd hitl && unzip -q ../hitl.zip -x '*/masks_human/*' '*/masks_machine/*'")
print("Fotos de autos en:", HITL, "-", len(glob.glob(f"{HITL}/**/img/*", recursive=True)), "fotos")
"""),
    code("""
# 4. Generar (en paralelo: una GPU con SDXL y otra con Kandinsky; LaMa en las dos)
os.makedirs(SALIDA, exist_ok=True)
planes = [("sdxl,lama", 0), ("kandinsky,lama", 1)] if N_GPU >= 2 else [(os.environ.get("EVX_EDITORES", "sdxl,lama"), 0)]
procs = []
for i, (editores, gpu) in enumerate(planes):
    log = open(f"{BASE}/generar_{i}.log", "w")
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": str(gpu)}
    cmd = [sys.executable, "training/generar_autos.py", "--hitl", HITL, "--salida", SALIDA, "--editores", editores,
           "--parte", str(i), "--partes", str(len(planes)), "--semilla", str(SEMILLA), "--max-horas", str(MAX_HORAS),
           "--lama-modelo", LAMA] + (["--limite", str(LIMITE)] if LIMITE else [])
    procs.append(subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env))
while any(p.poll() is None for p in procs):
    time.sleep(300)
    n = len(os.listdir(f"{SALIDA}/editadas")) if os.path.isdir(f"{SALIDA}/editadas") else 0
    print(time.strftime("%H:%M"), f"{n} fotos editadas", flush=True)
for i, p in enumerate(procs):
    print(f"--- proceso {i} (código {p.returncode}) ---")
    print("".join(open(f"{BASE}/generar_{i}.log").readlines()[-5:]))
if any(p.returncode for p in procs):
    raise SystemExit("Un proceso falló: mire el registro arriba.")
"""),
    code("""
# 5. Revisar a ojo: 8 ejemplos (original | editada | máscara)
import json, random
from PIL import Image
reg = [json.loads(x) for x in open(f"{SALIDA}/registro.jsonl", encoding="utf-8")]
print(len(reg), "ediciones:", {t: sum(r["tipo"] == t for r in reg) for t in ("borrar_dano", "agregar_dano", "cambiar_parte")},
      {e: sum(r["editor"] == e for r in reg) for e in ("sdxl", "kandinsky", "lama")})
filas = []
for r in random.Random(1).sample(reg, min(8, len(reg))):
    ims = [Image.open(f"{SALIDA}/originales/{r['original']}").convert("RGB"),
           Image.open(f"{SALIDA}/editadas/{r['editada']}").convert("RGB"),
           Image.open(f"{SALIDA}/mascaras/{r['editada']}").convert("RGB")]
    ims = [im.resize((int(im.width * 240 / im.height), 240)) for im in ims]
    fila = Image.new("RGB", (sum(i.width for i in ims) + 20, 240), "white")
    x = 0
    for im in ims:
        fila.paste(im, (x, 0)); x += im.width + 10
    filas.append(fila)
hoja = Image.new("RGB", (max(f.width for f in filas), 250 * len(filas)), "white")
for i, f in enumerate(filas):
    hoja.paste(f, (0, 250 * i))
os.makedirs("/kaggle/working" if os.path.isdir("/kaggle") else ".", exist_ok=True)
hoja.save(("/kaggle/working/" if os.path.isdir("/kaggle") else "") + "muestra_autos_ia.jpg", quality=85)
hoja
"""),
    code("""
# 6. Empaquetar (Output → evidex_autos_ia.zip; agréguelo como Input del notebook de entrenamiento)
destino = "/kaggle/working/evidex_autos_ia" if os.path.isdir("/kaggle") else "evidex_autos_ia"
shutil.make_archive(destino, "zip", SALIDA)
print("Listo:", destino + ".zip", round(os.path.getsize(destino + ".zip") / 1e9, 2), "GB")
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
                       "kaggle": {"accelerator": "nvidiaTeslaT4", "isInternetEnabled": True}}}
    destino = AQUI / "evidex_generar_autos.ipynb"
    destino.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print(destino)


if __name__ == "__main__":
    main()
