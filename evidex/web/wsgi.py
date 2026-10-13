"""Evidex en un servidor (VPS), detrás de Caddy o nginx con HTTPS.

    gunicorn --workers 1 --threads 8 --bind 127.0.0.1:8765 'evidex.web.wsgi:build()'

Variables de entorno:
  EVIDEX_DIR             carpeta de los casos (por defecto /var/lib/evidex/casos)
  EVIDEX_MODELO          carpeta del modelo de IA (la lee evidex/forensics/learned.py)
  EVIDEX_IPS_PERMITIDAS  opcional: redes desde donde se puede entrar a Evidex, separadas por coma
                         (por ejemplo «200.1.2.0/24,190.5.6.7»). El portal del asegurado (/c/...) queda abierto
                         a todos. Vacío = cualquier dirección (siempre con usuario y contraseña).
  EVIDEX_SOLO_ANALISIS   «1» para mostrar solo «Analizar archivos».

Un solo proceso (--workers 1) con varios hilos: el estado de los análisis en segundo plano vive en memoria.
"""
from __future__ import annotations

import ipaddress
import os
from pathlib import Path

from werkzeug.middleware.proxy_fix import ProxyFix

from evidex.web.app import create_app


def redes(texto: str) -> list:
    out = []
    for parte in (texto or "").replace(";", ",").split(","):
        parte = parte.strip()
        if parte:
            out.append(ipaddress.ip_network(parte, strict=False))
    return out


def build(env=os.environ):
    workdir = Path(env.get("EVIDEX_DIR") or "/var/lib/evidex/casos")
    app = create_app(workdir, {"PRODUCTION": True, "SERVER": True, "BACKGROUND_ANALYSIS": True,
                               "LEGACY_MODULES": env.get("EVIDEX_SOLO_ANALISIS") != "1",
                               "ALLOWED_NETWORKS": redes(env.get("EVIDEX_IPS_PERMITIDAS", ""))})
    # Caddy (en el mismo servidor) agrega la IP real del visitante, https y el dominio: se confía en un salto
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    return app

