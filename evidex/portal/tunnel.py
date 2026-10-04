"""Dirección pública para el portal del asegurado.

El enlace http://127.0.0.1:8765/... solo existe en el computador del analista: el celular del
asegurado no puede abrirlo y WhatsApp no lo muestra como enlace. Para la demo, Evidex abre un
túnel gratuito de Cloudflare (cloudflared) que entrega una dirección https://xxxx.trycloudflare.com
accesible desde cualquier celular. En producción se usa el dominio de la compañía (Configuración >
Dirección pública).

Por el túnel solo se puede abrir el portal (/c/...): el resto de Evidex sigue siendo local.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlparse

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def is_local(url: str) -> bool:
    """True si la dirección solo funciona en este computador (o en la red interna)."""
    host = (urlparse(url).hostname or "").lower()
    return host in LOCAL_HOSTS or host.startswith(("192.168.", "10.", "172.")) or not host


def is_temporary(url: str) -> bool:
    """True si es una dirección de prueba de Cloudflare: cambia cada vez que se reinicia Evidex."""
    return (urlparse(url).hostname or "").lower().endswith(".trycloudflare.com")


def find_cloudflared(base: Path) -> str | None:
    for c in (base / "cloudflared.exe", base / "cloudflared"):
        if c.exists():
            return str(c)
    return shutil.which("cloudflared")


def start(port: int, base: Path, timeout: float = 40) -> tuple[str | None, str]:
    """Inicia el túnel y devuelve (dirección pública, mensaje)."""
    exe = find_cloudflared(base)
    if not exe:
        return None, "No se encontró cloudflared. Use iniciar_publico.bat, que lo descarga."
    proc = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    found: list[str] = []
    ready = threading.Event()

    def read():
        for line in proc.stdout:
            if not found and (m := URL_RE.search(line)):
                found.append(m.group(0))
                ready.set()
        ready.set()
    threading.Thread(target=read, daemon=True).start()
    ready.wait(timeout)
    if not found:
        proc.terminate()
        return None, "No se pudo abrir el túnel (¿sin internet o bloqueado por la red de la empresa?)."
    return found[0], "ok"
