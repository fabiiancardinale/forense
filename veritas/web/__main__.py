"""Inicia la interfaz web de Veritas.

    python -m veritas.web                       # usa la carpeta ./casos
    python -m veritas.web --dir D:\casos --puerto 8765
    python -m veritas.web --publico             # portal del asegurado accesible desde internet (cloudflared)
"""
from __future__ import annotations

import argparse
import threading
import webbrowser
from pathlib import Path

from veritas.web.app import create_app


def main(argv=None):
    p = argparse.ArgumentParser(prog="veritas.web", description="Interfaz web local de Veritas")
    p.add_argument("--dir", default="casos", help="carpeta donde se guardan los casos (por defecto ./casos)")
    p.add_argument("--puerto", type=int, default=8765)
    p.add_argument("--no-abrir", action="store_true", help="no abrir el navegador automáticamente")
    p.add_argument("--red", action="store_true",
                   help="permitir que celulares de la misma red abran los enlaces de captura (HTTPS con certificado propio)")
    p.add_argument("--publico", action="store_true",
                   help="abrir un túnel https (cloudflared) para que el asegurado abra el enlace desde cualquier celular")
    a = p.parse_args(argv)
    app = create_app(Path(a.dir))
    url = f"http://127.0.0.1:{a.puerto}"
    if a.red:
        from veritas.portal.links import lan_ip
        url = f"https://127.0.0.1:{a.puerto}"
        app.config.update(LAN=True, PUBLIC_BASE=f"https://{lan_ip()}:{a.puerto}")
        print(f"Enlaces de captura disponibles en la red local: {app.config['PUBLIC_BASE']}")
        print("El navegador mostrará un aviso de certificado: es normal en la demo (Configuración avanzada > Continuar).")
    if a.publico and not a.red:
        from veritas.portal import tunnel
        print("Abriendo dirección pública para el portal del asegurado...")
        pub, msg = tunnel.start(a.puerto, Path.cwd())
        if pub:
            app.config.update(PUBLIC=True, PUBLIC_BASE=pub)
            print(f"Portal del asegurado disponible en internet: {pub}/c/...  (solo el portal; el resto sigue local)")
        else:
            print("AVISO: " + msg + " Los enlaces solo funcionarán en este computador.")
    print(f"Veritas está corriendo en {url}  (casos en {Path(a.dir).resolve()})")
    print("Para detenerlo, cierre esta ventana o presione Ctrl+C.")
    if not a.no_abrir:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    if a.red:
        app.run(host="0.0.0.0", port=a.puerto, debug=False, ssl_context="adhoc")
    else:
        app.run(host="127.0.0.1", port=a.puerto, debug=False)


if __name__ == "__main__":
    main()
