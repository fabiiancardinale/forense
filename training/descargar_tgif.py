"""Descarga una parte de TGIF (CC BY 4.0) sin bajar los archivos completos (algunos pesan 14 GB).

Lee el .tar.gz a medida que llega. OJO: dentro del archivo las fotos van ordenadas por tipo de objeto (unas 300
de botellas, luego 300 de sillones...). Tomar «las primeras N» deja solo 10 tipos y ningún auto. Por eso:
  --por-clase K           como máximo K fotos de cada tipo de objeto (recorre el archivo completo)
  --vehiculos V           como máximo V fotos de autos, camionetas, buses, motos y bicicletas (más que el resto)

  python training/descargar_tgif.py --destino datos/tgif --n 5000 --por-clase 60 --vehiculos 300
  python training/descargar_tgif.py --destino datos/tgif --n 500 --particion validation      (las primeras 500)

Origen: https://github.com/IDLabMedia/tgif-dataset (enlaces públicos de Nextcloud de IDLab, imec).
Cite el artículo de TGIF y respete CC BY 4.0 (atribución). No se bajan las variantes FLUX (licencia no comercial).
"""
from __future__ import annotations

import argparse
import tarfile
import time
import urllib.request
from collections import Counter
from pathlib import Path

BASE = "https://cloud.ilabt.imec.be/public.php/dav/files/xEeAzrY7ES9KA8o"
CARPETAS = ("orig", "sd2-sp", "sd2-fr", "sdxl-fr", "ps-sp")
VEHICULOS = {"car", "truck", "bus", "motorcycle", "bicycle"}


def clase(nombre: str) -> str:
    """«training/car/123_orig.png» -> «car»."""
    partes = nombre.split("/")
    return partes[-2] if len(partes) >= 2 else ""


def bajar(carpeta: str, particion: str, destino: Path, n: int, por_clase: int = 0, vehiculos: int = 0,
          abrir=None) -> Counter:
    """Devuelve cuántas imágenes se guardaron de cada tipo de objeto."""
    url = f"{BASE}/{carpeta}/{carpeta}_{particion}.tar.gz"
    abrir = abrir or (lambda: urllib.request.urlopen(
        urllib.request.Request(url, headers={"X-Requested-With": "XMLHttpRequest"}), timeout=120))
    tope = (lambda c: (vehiculos or por_clase) if c in VEHICULOS else por_clase) if por_clase else (lambda c: 0)
    k, por = 0, Counter()
    with abrir() as r, tarfile.open(fileobj=r, mode="r|gz") as t:
        for m in t:
            if not m.isfile():
                continue
            c = clase(m.name)
            if tope(c) and por[c] >= tope(c):
                continue                                   # ya hay suficientes de este tipo: se salta
            t.extract(m, destino / carpeta, filter="data")
            por[c] += 1
            k += 1
            if n and k >= n:
                break
    return por


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--destino", type=Path, required=True)
    ap.add_argument("--n", type=int, default=2000, help="imágenes por carpeta (0 = todas)")
    ap.add_argument("--particion", choices=("training", "validation", "testing"), default="training")
    ap.add_argument("--carpetas", default=",".join(CARPETAS))
    ap.add_argument("--por-clase", type=int, default=0, help="máximo por tipo de objeto (0 = sin balancear)")
    ap.add_argument("--vehiculos", type=int, default=0, help="máximo por tipo de vehículo (por defecto = --por-clase)")
    a = ap.parse_args()
    for c in a.carpetas.split(","):
        t = time.time()
        por = bajar(c, a.particion, a.destino, a.n, a.por_clase, a.vehiculos)
        veh = {k: v for k, v in por.items() if k in VEHICULOS}
        print(f"{c} {sum(por.values())} ({len(por)} tipos de objeto; vehículos {veh}) en {time.time() - t:.0f} s",
              flush=True)
    print("masks", sum(bajar("masks", a.particion, a.destino, 0).values()))   # las máscaras: todas


if __name__ == "__main__":
    main()
