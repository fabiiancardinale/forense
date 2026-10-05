"""Entrena el detector de ediciones con IA y lo exporta para Evidex.

  python training/entrenar.py --manifiesto manifiesto.csv --salida modelos/ --epocas 15 --preentrenado

Deja en --salida:
  evidex_ia.onnx         el modelo que carga Evidex (onnxruntime, sin torch en el servidor)
  evidex_ia.safetensors  los pesos, para seguir entrenando (no se usa pickle: un pickle puede ejecutar código)
  evidex_ia.json         ficha del modelo: conjuntos y licencias, umbral, métricas de validación, fecha

El umbral se elige en validación para que como máximo el --fpr de las ORIGINALES dé alerta (5 % por defecto).
Necesita GPU para un entrenamiento real (Kaggle/Colab gratis sirven); en CPU solo para probar que corre.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from datos import MAX_LADO, Recortes, degradar_fijo, dividir, leer, puntuar_mosaico  # noqa: E402
from modelo import ConPuntaje, EvidexNet, puntaje  # noqa: E402

FORMATO = 2          # 2 = mosaico a tamaño real (1 = foto entera achicada). Evidex revisa este número.


def perdida(logits, mask, etiqueta):
    m = F.interpolate(mask, size=logits.shape[-2:], mode="nearest")
    bce = F.binary_cross_entropy_with_logits(logits, m)
    p = torch.sigmoid(logits)
    dice = 1 - (2 * (p * m).sum((1, 2, 3)) + 1) / (p.sum((1, 2, 3)) + m.sum((1, 2, 3)) + 1)
    dice = (dice * etiqueta).sum() / etiqueta.sum().clamp(min=1)       # dice solo en editadas
    s = puntaje(logits).clamp(1e-4, 1 - 1e-4)
    img = F.binary_cross_entropy(s, etiqueta)
    return bce + dice + img


@torch.no_grad()
def evaluar(red, filas, disp, lado, paso):
    """Cada foto de validación entera, pasada por WhatsApp (1600 px, JPEG 70) y analizada en mosaico,
    igual que la analizará Evidex. Así el umbral queda calibrado para fotos completas."""
    from PIL import Image
    red.eval()

    def correr(t):
        logits = red(torch.from_numpy(t).to(disp))
        return torch.sigmoid(logits).cpu().numpy(), puntaje(logits).cpu().numpy()

    ps, ys, ious = [], [], []
    for f in filas:
        img = degradar_fijo(Image.open(f["ruta"]))
        s, mapa, esc = puntuar_mosaico(correr, img, lado, paso)
        ps.append(s)
        ys.append(f["etiqueta"])
        if f["etiqueta"]:
            if f["mascara"]:
                m = Image.open(f["mascara"]).convert("L").resize((mapa.shape[1], mapa.shape[0]), Image.NEAREST)
                m = np.asarray(m) > 127
            else:
                m = np.ones(mapa.shape, bool)
            a = mapa > .5
            union = (a | m).sum()
            ious.append(float((a & m).sum() / union) if union else 1.0)
    return np.array(ps), np.array(ys), float(np.mean(ious)) if ious else None


def umbral_para(ps, ys, fpr):
    orig = np.sort(ps[ys == 0])
    if len(orig) == 0:
        return .5
    k = int(np.floor(len(orig) * (1 - fpr)))
    return float(orig[min(k, len(orig) - 1)]) + 1e-6


def metricas(ps, ys, umbral):
    ed, ori = ps[ys == 1], ps[ys == 0]
    return {"deteccion_editadas": float((ed >= umbral).mean()) if len(ed) else None,
            "falsas_alarmas_originales": float((ori >= umbral).mean()) if len(ori) else None,
            "n_editadas": int(len(ed)), "n_originales": int(len(ori))}


def exportar(red, lado, destino: Path):
    red = red.cpu().eval()
    x = torch.zeros(1, 3, lado, lado)
    torch.onnx.export(ConPuntaje(red), (x,), str(destino), input_names=["imagen"],
                      output_names=["mapa", "puntaje"], opset_version=17, dynamo=False,
                      dynamic_axes={"imagen": {0: "n"}, "mapa": {0: "n"}, "puntaje": {0: "n"}})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifiesto", type=Path, required=True)
    ap.add_argument("--salida", type=Path, default=Path("modelos"))
    ap.add_argument("--encoder", default="efficientnet_b0")
    ap.add_argument("--preentrenado", action="store_true", help="partir de pesos ImageNet de timm")
    ap.add_argument("--lado", type=int, default=512)
    ap.add_argument("--epocas", type=int, default=15)
    ap.add_argument("--lote", type=int, default=12)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--fpr", type=float, default=.05, help="falsas alarmas máximas en originales (validación)")
    ap.add_argument("--limite", type=int, default=0, help="usar solo N imágenes (prueba rápida)")
    ap.add_argument("--trabajadores", type=int, default=2)
    ap.add_argument("--max-horas", type=float, default=0,
                    help="parar antes de este tiempo y exportar lo mejor (Kaggle corta a las 12 h)")
    ap.add_argument("--val-max", type=int, default=800, help="fotos de validación por época (las más lentas)")
    ap.add_argument("--continuar", type=Path, help="evidex_ia.safetensors de una vuelta anterior (mismo encoder)")
    a = ap.parse_args(argv)

    filas = leer(a.manifiesto)
    if a.limite:
        filas = filas[:a.limite // 2] + filas[-(a.limite - a.limite // 2):]
    entren, val = dividir(filas)
    disp = "cuda" if torch.cuda.is_available() else "cpu"
    red = EvidexNet(a.encoder, a.preentrenado and not a.continuar)
    if a.continuar:
        from safetensors.torch import load_file
        red.load_state_dict(load_file(str(a.continuar)))
        print(f"Continuando desde {a.continuar}", flush=True)
    red = red.to(disp)
    inicio, ultima = time.time(), 0.0
    opt = torch.optim.AdamW(red.parameters(), lr=a.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, a.epocas))
    paso = a.lado * 3 // 4                       # los pedazos se traslapan un cuarto
    ds = Recortes(entren, a.lado)
    import random as _r
    val = sorted(val, key=lambda f: f["ruta"])
    _r.Random(1).shuffle(val)
    val = [f for f in val if f["etiqueta"] == 0][:a.val_max // 2] + [f for f in val if f["etiqueta"]][:a.val_max // 2]
    mejor, hist = None, []
    a.salida.mkdir(parents=True, exist_ok=True)
    for ep in range(a.epocas):
        if a.max_horas and time.time() - inicio + ultima * 1.1 > a.max_horas * 3600:
            print(f"Se acaba el tiempo ({a.max_horas} h): se para en la época {ep} y se exporta lo mejor.", flush=True)
            break
        ds.epoca = ep
        red.train()
        t, tot = time.time(), 0.0
        for x, m, y in DataLoader(ds, batch_size=a.lote, shuffle=True, num_workers=a.trabajadores, drop_last=True):
            loss = perdida(red(x.to(disp)), m.to(disp), y.to(disp))
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += loss.item()
        sched.step()
        ps, ys, iou = evaluar(red, val, disp, a.lado, paso)
        u = umbral_para(ps, ys, a.fpr)
        met = {**metricas(ps, ys, u), "iou_zona": iou, "umbral": u}
        hist.append({"epoca": ep + 1, "perdida": tot, **met})
        ultima = time.time() - t
        print(json.dumps(hist[-1], ensure_ascii=False), f"({ultima:.0f}s)", flush=True)
        if mejor is None or (met["deteccion_editadas"] or 0) > (mejor["deteccion_editadas"] or 0):
            mejor = met
            from safetensors.torch import save_file
            save_file({k: v.contiguous().cpu() for k, v in red.state_dict().items()},
                      str(a.salida / "evidex_ia.safetensors"))

    from safetensors.torch import load_file
    red.load_state_dict(load_file(str(a.salida / "evidex_ia.safetensors")))
    exportar(red, a.lado, a.salida / "evidex_ia.onnx")
    conjuntos = Counter((f["conjunto"].split("/")[0], f["licencia"]) for f in filas)
    ficha = {
        "formato": FORMATO, "nombre": "Evidex IA (zonas editadas con IA)", "encoder": a.encoder,
        "preentrenado": "ImageNet (timm)" if a.preentrenado else None,
        "continuado_desde": str(a.continuar) if a.continuar else None, "lado": a.lado,
        "modo": "mosaico", "paso": paso, "max_lado": MAX_LADO,
        "normalizacion": "imagenet", "umbral": mejor["umbral"], "fpr_objetivo": a.fpr,
        "validacion": mejor, "historial": hist,
        "conjuntos": [{"nombre": n, "licencia": l, "imagenes": c} for (n, l), c in sorted(conjuntos.items())],
        "aumentos": "como WhatsApp: reducción 640-2048 px, JPEG 50-92 (a veces doble), recorte leve, espejo; "
                    "recortes a tamaño real (60 % sobre la zona editada)",
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sha256_onnx": hashlib.sha256((a.salida / "evidex_ia.onnx").read_bytes()).hexdigest(),
        "advertencia": "Indicio para revisar, no prueba. Validar con fotos reales de siniestros antes de usar.",
    }
    (a.salida / "evidex_ia.json").write_text(json.dumps(ficha, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Listo: {a.salida / 'evidex_ia.onnx'}  umbral={mejor['umbral']:.3f}  validación={mejor}")


if __name__ == "__main__":
    main()
