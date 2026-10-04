"""Genera training/evidex_kaggle.ipynb: notebook listo para Kaggle («Run all»), sin depender de GitHub.

El código de entrenamiento va dentro del notebook, así sirve aunque el repositorio sea privado.
  python training/hacer_notebook.py
"""
import json
from pathlib import Path

AQUI = Path(__file__).resolve().parent
ARCHIVOS = ("datos.py", "modelo.py", "entrenar.py", "descargar_tgif.py")


def md(texto):
    return {"cell_type": "markdown", "metadata": {}, "source": texto.strip("\n").splitlines(True)}


def code(texto):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": texto.strip("\n").splitlines(True)}


CELDAS = [md("""
# Evidex: entrenar el detector de ediciones con IA

Antes de empezar, en el panel derecho (**Settings**):
1. **Accelerator:** GPU T4 x2 (o P100).
2. **Internet:** activado (para bajar TGIF; Kaggle pide verificar su teléfono).

Después: **Run all**. Tarda unas 2 a 4 horas. Al final descargue `evidex_modelo.zip` desde la pestaña
**Output** (a la derecha) y copie los 3 archivos a `veritas\\modelos\\` en su PC.

Datos: TGIF (IDLab, imec), CC BY 4.0, https://github.com/IDLabMedia/tgif-dataset. Se excluyen las variantes FLUX
(licencia no comercial). Fotos propias (opcional): suba un *Dataset* de Kaggle con las carpetas `originales/`,
`editadas/` y opcionalmente `mascaras/`, y agréguelo al notebook con **+ Add Input**. Solo fotos suyas o con permiso.
"""),
    code("""
# 1. Configuración (puede cambiar estos números)
import os
N_POR_CARPETA = int(os.environ.get("EVX_N", 2000))     # imágenes de TGIF por carpeta
CARPETAS = os.environ.get("EVX_CARPETAS", "orig,sd2-sp,sdxl-fr")
EPOCAS = int(os.environ.get("EVX_EPOCAS", 15))
LADO = int(os.environ.get("EVX_LADO", 512))
LOTE = int(os.environ.get("EVX_LOTE", 16))
N_PRUEBA = int(os.environ.get("EVX_N_PRUEBA", 300))   # fotos de la partición «testing» para medir al final
PREENTRENADO = os.environ.get("EVX_PREENTRENADO", "1") == "1"   # pesos ImageNet de timm (ver licencias)
DATOS = os.environ.get("EVX_DATOS", "/kaggle/temp/tgif" if os.path.isdir("/kaggle") else "datos_tgif")
SALIDA = os.environ.get("EVX_SALIDA", "/kaggle/working/modelos" if os.path.isdir("/kaggle") else "modelos")
"""),
    code("""
# 2. Preparar el entorno
import subprocess, sys, shutil
def sh(cmd):
    print("$", cmd, flush=True)
    r = subprocess.run(cmd, shell=True)
    if r.returncode:
        raise SystemExit(f"Falló: {cmd}")
sh(f"{sys.executable} -m pip install -q timm safetensors onnx onnxruntime")
import torch
print("GPU:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "NO HAY GPU (active el acelerador en Settings)")
print(shutil.disk_usage("/kaggle" if os.path.isdir("/kaggle") else "."))
"""),
    code("""
# 3. Código de entrenamiento de Evidex (copiado de training/ del repositorio)
from pathlib import Path
Path("training").mkdir(exist_ok=True)
ARCHIVOS = __ARCHIVOS__
for nombre, contenido in ARCHIVOS.items():
    Path("training", nombre).write_text(contenido, encoding="utf-8")
print("Archivos:", ", ".join(ARCHIVOS))
"""),
    code("""
# 4. Bajar una parte de TGIF (lee el .tar.gz mientras llega; no baja los 14 GB completos)
sh(f"{sys.executable} training/descargar_tgif.py --destino {DATOS} --n {N_POR_CARPETA} --particion training --carpetas {CARPETAS}")
"""),
    code("""
# 5. Manifiesto: qué imágenes se usan y con qué licencia (se niega si hay alguna no comercial)
import glob
propias = [os.path.dirname(p) for p in glob.glob("/kaggle/input/*/originales") + glob.glob("/kaggle/input/*/*/originales")]
extra = " ".join(f"--propias {p}" for p in propias)
print("Fotos propias:", propias or "ninguna")
sh(f"{sys.executable} training/datos.py --tgif {DATOS} {extra} --salida manifiesto.csv")
"""),
    code("""
# 6. Entrenar (aquí se van las horas; cada época imprime cuántas editadas detecta en validación)
pre = "--preentrenado" if PREENTRENADO else ""
sh(f"{sys.executable} training/entrenar.py --manifiesto manifiesto.csv --salida {SALIDA} "
   f"--epocas {EPOCAS} --lado {LADO} --lote {LOTE} --trabajadores 4 {pre}")
"""),
    code("""
# 7. Medir con fotos que el modelo nunca vio (partición «testing»), pasadas por WhatsApp
import io, json, numpy as np, onnxruntime as ort
from PIL import Image
sys.path.insert(0, "training")
from datos import a_tensor
PRUEBA = DATOS + "_prueba"
sh(f"{sys.executable} training/descargar_tgif.py --destino {PRUEBA} --n {N_PRUEBA} --particion testing --carpetas orig,sd2-sp,sdxl-fr")
ficha = json.load(open(f"{SALIDA}/evidex_ia.json"))
sess = ort.InferenceSession(f"{SALIDA}/evidex_ia.onnx", providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
def whatsapp(p):
    im = Image.open(p).convert("RGB"); im.thumbnail((1600, 1600))
    b = io.BytesIO(); im.save(b, "JPEG", quality=70)
    return Image.open(io.BytesIO(b.getvalue()))
def puntajes(carpeta):
    out = []
    for p in sorted(glob.glob(f"{PRUEBA}/{carpeta}/**/*.png", recursive=True)):
        x = a_tensor(whatsapp(p), ficha["lado"])[None]
        out.append(float(sess.run(["puntaje"], {"imagen": x})[0][0]))
    return np.array(out)
u = ficha["umbral"]
res = {c: puntajes(c) for c in ("orig", "sd2-sp", "sdxl-fr")}
medicion = {"umbral": u,
            "falsas_alarmas_originales": f"{(res['orig'] >= u).sum()} de {len(res['orig'])}",
            "detectadas_sd2_zona": f"{(res['sd2-sp'] >= u).sum()} de {len(res['sd2-sp'])}",
            "detectadas_sdxl_regenerada": f"{(res['sdxl-fr'] >= u).sum()} de {len(res['sdxl-fr'])}",
            "linea_base_evidex_hoy": "2-7 de cada 100 editadas pasadas por WhatsApp"}
ficha["prueba_testing_whatsapp"] = medicion
json.dump(ficha, open(f"{SALIDA}/evidex_ia.json", "w"), indent=2, ensure_ascii=False)   # el sha256 es del .onnx: sigue válido
print(json.dumps(medicion, indent=2, ensure_ascii=False))
"""),
    code("""
# 8. Empaquetar para descargar (pestaña Output → evidex_modelo.zip)
shutil.make_archive(os.path.join(os.path.dirname(SALIDA) or ".", "evidex_modelo"), "zip", SALIDA)
print("Listo. Descargue evidex_modelo.zip y copie su contenido a veritas\\\\modelos\\\\ en su PC.")
print(sorted(os.listdir(SALIDA)))
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
                       "kaggle": {"accelerator": "gpu", "isInternetEnabled": True}}}
    destino = AQUI / "evidex_kaggle.ipynb"
    destino.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print(destino)


if __name__ == "__main__":
    main()
