"""Genera fotos de autos editadas con IA, con la máscara exacta de lo cambiado, para entrenar a Evidex.

No existe un conjunto público de autos editados con IA. Este script lo fabrica:
  - Fotos: «Car parts and car damages» de Humans in the Loop (1.812 fotos, CC0 1.0: dominio público, uso comercial
    libre). Trae polígonos de 21 partes del auto y 8 tipos de daño.
  - Editores (licencias que permiten uso comercial):
      sdxl       SDXL inpainting 0.1 (diffusers, OpenRAIL++-M: respetar sus restricciones de uso)
      kandinsky  Kandinsky 2.2 inpainting (Apache 2.0)
      lama       LaMa (Apache 2.0), un «borrador de objetos» como el de las galerías de los teléfonos
  - Ediciones, como las haría un asegurado:
      borrar_dano    se borra un daño real (abolladura, rayón, trizadura...)
      agregar_dano   se agrega un daño a una parte sana (puerta, tapabarro, parachoques, capó...)
      cambiar_parte  se rehace un foco, espejo, patente, parrilla o llanta
    Igual que en el teléfono, la IA trabaja sobre un recorte alrededor de la zona y el resultado se pega en la foto
    original: fuera de la máscara los píxeles quedan idénticos.

Salida (formato de fotos propias de training/datos.py):
  salida/originales/hitl0001.jpg          la foto tal cual
  salida/editadas/hitl0001_agregar_dano_sdxl.png
  salida/mascaras/hitl0001_agregar_dano_sdxl.png   (blanco = cambiado)
  salida/registro.jsonl                   qué se hizo en cada una (editor, prompt, parte, semilla)
  salida/licencia.txt

  python training/generar_autos.py --hitl datos/hitl --salida datos/autos_ia --editores sdxl,lama --parte 0 --partes 2
Necesita GPU para sdxl y kandinsky; lama corre también en CPU.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

DANOS = {"Missing part", "Broken part", "Scratch", "Cracked", "Dent", "Flaking", "Paint chip", "Corrosion"}
CARROCERIA = {"Front-door", "Back-door", "Fender", "Quarter-panel", "Hood", "Trunk", "Front-bumper", "Back-bumper",
              "Rocker-panel", "Roof"}
PIEZAS = {"Headlight": "a broken shattered car headlight", "Tail-light": "a cracked broken car tail light",
          "Mirror": "a broken car side mirror hanging", "License-plate": "a car license plate",
          "Grille": "a damaged cracked car front grille", "Front-wheel": "a car wheel with a scratched bent rim",
          "Back-wheel": "a car wheel with a scratched bent rim"}
DANO_PROMPT = ["a deep dent in the car {p}, crumpled metal", "long deep scratches on the car {p} paint",
               "cracked paint and a dent on the car {p}", "a crushed damaged car {p} after a collision",
               "a broken cracked plastic car {p}"]
LIMPIO = "clean undamaged car {p}, smooth glossy paint, no dents, no scratches"
NEGATIVO = "text, watermark, logo, cartoon, drawing, blurry, low quality"
PARTES_ES = {"Front-door": "door", "Back-door": "door", "Fender": "fender", "Quarter-panel": "quarter panel",
             "Hood": "hood", "Trunk": "trunk", "Front-bumper": "front bumper", "Back-bumper": "rear bumper",
             "Rocker-panel": "side skirt", "Roof": "roof"}
LICENCIA = ("Fotos: Humans in the Loop «Car parts and car damages», CC0 1.0 (dominio público). "
            "Ediciones: SDXL inpainting 0.1 (OpenRAIL++-M), Kandinsky 2.2 (Apache 2.0), LaMa (Apache 2.0)")
GENERATIVOS = ("sdxl", "kandinsky")


# ---- fotos y anotaciones (formato Supervisely: img/<foto> + ann/<foto>.json) -------------------------------
def listar(raiz: Path) -> list[dict]:
    items = []
    for ann in sorted(raiz.rglob("ann/*.json")):
        img = ann.parent.parent / "img" / ann.name[:-5]
        if not img.exists():
            continue
        try:
            data = json.loads(ann.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        objs = [{"clase": o.get("classTitle"), "poligono": [tuple(p) for p in (o.get("points") or {}).get("exterior") or []]}
                for o in data.get("objects") or [] if o.get("geometryType") == "polygon"]
        objs = [o for o in objs if len(o["poligono"]) >= 3]
        if objs:
            items.append({"img": img, "objetos": objs})
    return items


def mascara_poligono(tam, poligono, dilatar: int = 0) -> Image.Image:
    m = Image.new("L", tam, 0)
    ImageDraw.Draw(m).polygon(poligono, fill=255)
    if dilatar:
        m = m.filter(ImageFilter.MaxFilter(dilatar * 2 + 1))
    return m


def mancha_dentro(tam, poligono, rng: random.Random) -> Image.Image:
    """Una zona irregular dentro de una parte de la carrocería (donde se «agrega» un daño)."""
    parte = np.asarray(mascara_poligono(tam, poligono)) > 0
    ys, xs = np.nonzero(parte)
    if len(xs) < 50:
        return Image.new("L", tam, 0)
    w, h = xs.max() - xs.min(), ys.max() - ys.min()
    k = rng.randrange(len(xs))
    cx, cy = xs[k], ys[k]
    m = Image.new("L", tam, 0)
    d = ImageDraw.Draw(m)
    for _ in range(rng.randint(2, 4)):                       # varias elipses = forma irregular
        rx, ry = w * rng.uniform(.08, .22), h * rng.uniform(.08, .22)
        ox, oy = rng.uniform(-rx, rx) * .6, rng.uniform(-ry, ry) * .6
        d.ellipse([cx + ox - rx, cy + oy - ry, cx + ox + rx, cy + oy + ry], fill=255)
    return Image.fromarray(((np.asarray(m) > 0) & parte).astype(np.uint8) * 255)


def planificar(item: dict, idx: int, editores: list[str], semilla: int) -> list[dict]:
    """Qué ediciones se le hacen a una foto (siempre las mismas para la misma foto y semilla)."""
    rng = random.Random(semilla * 100003 + idx)
    gen = [e for e in editores if e in GENERATIVOS]
    danos = [o for o in item["objetos"] if o["clase"] in DANOS]
    cuerpo = [o for o in item["objetos"] if o["clase"] in CARROCERIA]
    piezas = [o for o in item["objetos"] if o["clase"] in PIEZAS]
    trabajos = []
    if danos:
        o = rng.choice(danos)
        borrador = "lama" if "lama" in editores and (not gen or rng.random() < .5) else (rng.choice(gen) if gen else None)
        if borrador:
            parte = rng.choice([PARTES_ES[c["clase"]] for c in cuerpo]) if cuerpo else "body panel"
            trabajos.append({"tipo": "borrar_dano", "editor": borrador, "clase": o["clase"], "poligono": o["poligono"],
                             "prompt": LIMPIO.format(p=parte)})
    if cuerpo and gen:
        o = rng.choice(cuerpo)
        trabajos.append({"tipo": "agregar_dano", "editor": rng.choice(gen), "clase": o["clase"], "poligono": o["poligono"],
                         "prompt": rng.choice(DANO_PROMPT).format(p=PARTES_ES[o["clase"]])})
    if piezas and gen and rng.random() < .35:
        o = rng.choice(piezas)
        trabajos.append({"tipo": "cambiar_parte", "editor": rng.choice(gen), "clase": o["clase"], "poligono": o["poligono"],
                         "prompt": PIEZAS[o["clase"]]})
    for t in trabajos:
        t["semilla"] = rng.randrange(2 ** 31)
    return trabajos


def mascara_de(trabajo: dict, tam) -> Image.Image:
    if trabajo["tipo"] == "agregar_dano":
        return mancha_dentro(tam, trabajo["poligono"], random.Random(trabajo["semilla"]))
    return mascara_poligono(tam, trabajo["poligono"], dilatar=max(3, min(tam) // 120))


def ventana(mask: np.ndarray, lado: int):
    """Recorte cuadrado alrededor de la zona (lo que hace el teléfono antes de mandar a la IA)."""
    h, w = mask.shape
    ys, xs = np.nonzero(mask)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    s = int(max(x1 - x0, y1 - y0) * 1.6)
    s = min(max(s, min(lado, w, h)), w, h)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    bx = int(min(max(cx - s // 2, 0), w - s))
    by = int(min(max(cy - s // 2, 0), h - s))
    return bx, by, bx + s, by + s


def pegar(orig: Image.Image, gen: Image.Image, mask: Image.Image, caja) -> tuple[Image.Image, Image.Image]:
    """Pega el recorte editado sobre la foto original, solo dentro de la máscara (borde suavizado)."""
    alfa = mask.crop(caja).filter(ImageFilter.GaussianBlur(2))
    out = orig.copy()
    out.paste(gen.resize(alfa.size, Image.LANCZOS), caja[:2], alfa)
    final = Image.new("L", orig.size, 0)
    final.paste(alfa.point(lambda v: 255 if v > 0 else 0), caja[:2])        # todo píxel que cambió, aunque sea poco
    return out, final


# ---- editores ------------------------------------------------------------------------------------------
class Lama:
    URL = "https://github.com/enesmsahin/simple-lama-inpainting/releases/download/v0.1.0/big-lama.pt"
    lado = 512

    def __init__(self, dispositivo: str, modelo: Path | None = None):
        import torch
        import urllib.request
        self.torch, self.disp = torch, dispositivo
        if modelo is None or not Path(modelo).exists():
            modelo = Path(modelo or "big-lama.pt")
            if not modelo.exists():
                urllib.request.urlretrieve(self.URL, modelo)
        self.m = torch.jit.load(str(modelo), map_location=dispositivo).eval()

    def __call__(self, img: Image.Image, mask: Image.Image, prompt: str, semilla: int) -> Image.Image:
        t = self.torch
        w, h = img.size
        W, H = (w + 7) // 8 * 8, (h + 7) // 8 * 8
        a = np.zeros((H, W, 3), np.float32)
        a[:h, :w] = np.asarray(img, np.float32) / 255
        m = np.zeros((H, W), np.float32)
        m[:h, :w] = (np.asarray(mask) > 0)
        with t.no_grad():
            out = self.m(t.from_numpy(a.transpose(2, 0, 1))[None].to(self.disp),
                         t.from_numpy(m)[None, None].to(self.disp))
        r = np.clip(out[0].permute(1, 2, 0).cpu().numpy() * 255, 0, 255).astype(np.uint8)
        return Image.fromarray(r[:h, :w])


class Difusor:
    def __init__(self, nombre: str, dispositivo: str):
        import torch
        from diffusers import AutoPipelineForInpainting
        self.torch, self.disp = torch, dispositivo
        repo, self.lado, kw = {
            "sdxl": ("diffusers/stable-diffusion-xl-1.0-inpainting-0.1", 1024, {"variant": "fp16"}),
            "kandinsky": ("kandinsky-community/kandinsky-2-2-decoder-inpaint", 768, {}),
        }[nombre]
        self.nombre = nombre
        import os
        self.lado = int(os.environ.get("EVX_LADO_GEN", self.lado))           # solo para pruebas en CPU
        self.pasos = int(os.environ.get("EVX_PASOS_GEN", 25))
        dtype = torch.float16 if dispositivo == "cuda" else torch.float32
        if dtype == torch.float32:
            kw = {}
        self.pipe = AutoPipelineForInpainting.from_pretrained(repo, torch_dtype=dtype, **kw).to(dispositivo)
        self.pipe.set_progress_bar_config(disable=True)

    def __call__(self, img: Image.Image, mask: Image.Image, prompt: str, semilla: int) -> Image.Image:
        L = self.lado
        g = self.torch.Generator(device=self.disp).manual_seed(semilla)
        kw = {"strength": .99} if self.nombre == "sdxl" else {}
        out = self.pipe(prompt=prompt, negative_prompt=NEGATIVO, image=img.resize((L, L), Image.LANCZOS),
                        mask_image=mask.resize((L, L), Image.NEAREST), height=L, width=L,
                        num_inference_steps=self.pasos, guidance_scale=7.5, generator=g, **kw).images[0]
        return out.resize(img.size, Image.LANCZOS)


def cargar_editor(nombre: str, dispositivo: str, lama_modelo: Path | None = None):
    return Lama(dispositivo, lama_modelo) if nombre == "lama" else Difusor(nombre, dispositivo)


# ---- todo junto ----------------------------------------------------------------------------------------
def generar(items: list[dict], salida: Path, editores: dict, parte: int = 0, partes: int = 1, semilla: int = 0,
            max_horas: float = 0, limite: int = 0) -> int:
    for d in ("originales", "editadas", "mascaras"):
        (salida / d).mkdir(parents=True, exist_ok=True)
    (salida / "licencia.txt").write_text(LICENCIA, encoding="utf-8")
    inicio, hechas = time.time(), 0
    with (salida / "registro.jsonl").open("a", encoding="utf-8") as reg:
        for idx, item in enumerate(items):
            if idx % partes != parte:
                continue
            if (max_horas and time.time() - inicio > max_horas * 3600) or (limite and hechas >= limite):
                break
            base = f"hitl{idx:04d}"
            trabajos = planificar(item, idx, list(editores), semilla)
            if not trabajos:
                continue
            try:
                orig = Image.open(item["img"]).convert("RGB")
            except OSError:
                continue
            dst = salida / "originales" / (base + item["img"].suffix.lower())
            if not dst.exists():
                shutil.copyfile(item["img"], dst)
            for t in trabajos:
                stem = f"{base}_{t['tipo']}_{t['editor']}"
                if (salida / "editadas" / f"{stem}.png").exists():
                    continue                                      # ya hecha (se puede retomar)
                mask = mascara_de(t, orig.size)
                frac = (np.asarray(mask) > 0).mean()
                if not .002 <= frac <= .35:
                    continue
                editor = editores[t["editor"]]
                caja = ventana(np.asarray(mask) > 0, getattr(editor, "lado", 512))
                gen = editor(orig.crop(caja), mask.crop(caja), t["prompt"], t["semilla"])
                editada, final = pegar(orig, gen, mask, caja)
                editada.save(salida / "editadas" / f"{stem}.png")
                final.save(salida / "mascaras" / f"{stem}.png")
                reg.write(json.dumps({"editada": f"{stem}.png", "original": dst.name, "foto_fuente": item["img"].name,
                                      **{k: t[k] for k in ("tipo", "editor", "clase", "prompt", "semilla")},
                                      "area": round(float(frac), 4)}, ensure_ascii=False) + "\n")
                reg.flush()
                hechas += 1
    return hechas


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hitl", type=Path, required=True, help="carpeta del conjunto de Humans in the Loop (descomprimido)")
    ap.add_argument("--salida", type=Path, required=True)
    ap.add_argument("--editores", default="sdxl,kandinsky,lama")
    ap.add_argument("--parte", type=int, default=0, help="para repartir entre varias GPU: esta parte...")
    ap.add_argument("--partes", type=int, default=1, help="...de cuántas")
    ap.add_argument("--semilla", type=int, default=0)
    ap.add_argument("--max-horas", type=float, default=0)
    ap.add_argument("--limite", type=int, default=0, help="como máximo N ediciones (prueba rápida)")
    ap.add_argument("--lama-modelo", type=Path)
    a = ap.parse_args(argv)
    import torch
    disp = "cuda" if torch.cuda.is_available() else "cpu"
    items = listar(a.hitl)
    print(f"{len(items)} fotos con anotaciones; editores {a.editores}; parte {a.parte}/{a.partes}; {disp}", flush=True)
    editores = {e: cargar_editor(e, disp, a.lama_modelo) for e in a.editores.split(",") if e}
    t = time.time()
    n = generar(items, a.salida, editores, a.parte, a.partes, a.semilla, a.max_horas, a.limite)
    print(f"Listo: {n} ediciones en {time.time() - t:.0f} s -> {a.salida}", flush=True)


if __name__ == "__main__":
    main()
