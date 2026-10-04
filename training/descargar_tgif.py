"""Descarga una parte de TGIF (CC BY 4.0) sin bajar los archivos completos (algunos pesan 14 GB).

Lee el .tar.gz a medida que llega y se detiene al tener N imágenes de cada carpeta.
  python training/descargar_tgif.py --destino datos/tgif --n 3000 --particion training
  python training/descargar_tgif.py --destino datos/tgif --n 500  --particion validation

Origen: https://github.com/IDLabMedia/tgif-dataset (enlaces públicos de Nextcloud de IDLab, imec).
Cite el artículo de TGIF y respete CC BY 4.0 (atribución). No se bajan las variantes FLUX (licencia no comercial).
"""
from __future__ import annotations

import argparse
import tarfile
import urllib.request
from pathlib import Path

BASE = "https://cloud.ilabt.imec.be/public.php/dav/files/xEeAzrY7ES9KA8o"
CARPETAS = ("orig", "sd2-sp", "sd2-fr", "sdxl-fr", "ps-sp")


def bajar(carpeta: str, particion: str, destino: Path, n: int) -> int:
    url = f"{BASE}/{carpeta}/{carpeta}_{particion}.tar.gz"
    req = urllib.request.Request(url, headers={"X-Requested-With": "XMLHttpRequest"})
    k = 0
    with urllib.request.urlopen(req, timeout=120) as r, tarfile.open(fileobj=r, mode="r|gz") as t:
        for m in t:
            if not m.isfile():
                continue
            t.extract(m, destino / carpeta, filter="data")
            k += 1
            if n and k >= n:
                break
    return k


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--destino", type=Path, required=True)
    ap.add_argument("--n", type=int, default=2000, help="imágenes por carpeta (0 = todas)")
    ap.add_argument("--particion", choices=("training", "validation", "testing"), default="training")
    ap.add_argument("--carpetas", default=",".join(CARPETAS))
    a = ap.parse_args()
    for c in a.carpetas.split(","):
        print(c, bajar(c, a.particion, a.destino, a.n), flush=True)
    print("masks", bajar("masks", a.particion, a.destino, 0))      # las máscaras pesan poco: todas


if __name__ == "__main__":
    main()
