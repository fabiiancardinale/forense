"""Red del detector: codificador timm + decodificador tipo FPN liviano.

Salida: un mapa (logits, 1 canal, 1/4 de la resolución de entrada) de «zona editada con IA».
El puntaje de la imagen se calcula del mapa (promedio del 1 % de píxeles más altos), así la imagen y la zona
salen de lo mismo y el analista siempre ve DÓNDE está el indicio.

Codificador por defecto: efficientnet_b0 (código Apache 2.0). Con --preentrenado se descargan pesos ImageNet
de timm; revise sus condiciones antes de vender el modelo (ver training/README.md).
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class EvidexNet(nn.Module):
    def __init__(self, encoder: str = "efficientnet_b0", preentrenado: bool = False, canales: int = 96):
        super().__init__()
        import timm
        self.encoder = timm.create_model(encoder, features_only=True, pretrained=preentrenado,
                                         out_indices=(1, 2, 3, 4))
        chs = self.encoder.feature_info.channels()
        self.lat = nn.ModuleList(nn.Conv2d(c, canales, 1) for c in chs)
        self.suave = nn.Sequential(nn.Conv2d(canales, canales, 3, padding=1), nn.BatchNorm2d(canales),
                                   nn.ReLU(inplace=True), nn.Conv2d(canales, 1, 1))

    def forward(self, x):
        feats = self.encoder(x)
        y = self.lat[-1](feats[-1])
        for f, lat in zip(reversed(feats[:-1]), reversed(self.lat[:-1])):
            y = F.interpolate(y, size=f.shape[-2:], mode="bilinear", align_corners=False) + lat(f)
        return self.suave(y)                                  # (N,1,H/4,W/4) logits


def puntaje(logits: torch.Tensor, frac: float = .01) -> torch.Tensor:
    """Puntaje 0..1 por imagen: media del `frac` de píxeles más sospechosos."""
    p = torch.sigmoid(logits).flatten(1)
    k = max(1, int(p.shape[1] * frac))
    return p.topk(k, dim=1).values.mean(1)


class ConPuntaje(nn.Module):
    """Lo que se exporta a ONNX: devuelve (mapa de probabilidad, puntaje)."""

    def __init__(self, red: EvidexNet):
        super().__init__()
        self.red = red

    def forward(self, x):
        logits = self.red(x)
        return torch.sigmoid(logits), puntaje(logits)
