"""Inicia la interfaz web de Evidex.

    python -m evidex.web                       # usa la carpeta ./casos
    python -m evidex.web --dir D:\casos --puerto 8765
    python -m evidex.web --publico             # portal del asegurado accesible desde internet (cloudflared)
"""
from __future__ import annotations

import argparse
import threading
import subprocess
import sys
import webbrowser
from pathlib import Path

from evidex.web.app import create_app


def main(argv=None):
    p = argparse.ArgumentParser(prog="evidex.web", description="Interfaz web local de Evidex")
    p.add_argument("--dir", default="casos", help="carpeta donde se guardan los casos (por defecto ./casos)")
    p.add_argument("--puerto", type=int, default=8765)
    p.add_argument("--no-abrir", action="store_true", help="no abrir el navegador automáticamente")
    p.add_argument("--red", action="store_true",
                   help="permitir que celulares de la misma red abran los enlaces de captura (HTTPS con certificado propio)")
    p.add_argument("--publico", action="store_true",
                   help="abrir un túnel https (cloudflared) para que el asegurado abra el enlace desde cualquier celular")
    p.add_argument("--solo-analisis", action="store_true",
                   help="mostrar solo «Analizar archivos» (sin siniestros, portal, investigaciones ni cartera)")
    p.add_argument("--legacy", action="store_true", help=argparse.SUPPRESS)   # compatibilidad: ya viene activo
    p.add_argument("--demo", action="store_true", help="habilitar explícitamente demo sin usuarios, solo local")
    p.add_argument("--sin-worker", action="store_true", help="worker administrado por separado")
    a = p.parse_args(argv)
    if a.demo and (a.red or a.publico):
        p.error("La demo anónima solo se permite en localhost.")
    app = create_app(Path(a.dir), {"DEMO_MODE": a.demo, "LEGACY_MODULES": not a.solo_analisis,
                                     "BACKGROUND_ANALYSIS": True})
    url = f"http://127.0.0.1:{a.puerto}"
    if a.red:
        from evidex.portal.links import lan_ip
        url = f"https://127.0.0.1:{a.puerto}"
        app.config.update(LAN=True, PUBLIC_BASE=f"https://{lan_ip()}:{a.puerto}")
        print(f"Enlaces de captura disponibles en la red local: {app.config['PUBLIC_BASE']}")
        print("El navegador mostrará un aviso de certificado: es normal en la demo (Configuración avanzada > Continuar).")
    if a.publico and not a.red:
        from evidex.portal import tunnel
        print("Abriendo dirección pública para el portal del asegurado...")
        pub, msg = tunnel.start(a.puerto, Path.cwd())
        if pub:
            app.config.update(PUBLIC=True, PUBLIC_BASE=pub)
            print(f"Portal del asegurado disponible en internet: {pub}/c/...  (solo el portal; el resto sigue local)")
        else:
            print("AVISO: " + msg + " Los enlaces solo funcionarán en este computador.")
    print(f"Evidex está corriendo en {url}  (casos en {Path(a.dir).resolve()})")
    print("Para detenerlo, cierre esta ventana o presione Ctrl+C.")
    if not a.no_abrir:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    worker = None
    if not a.sin_worker:
        worker = subprocess.Popen([sys.executable, '-m', 'evidex.inspection.worker', '--dir', str(Path(a.dir).resolve())])
    import atexit
    def stop_worker():
        if worker and worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.kill()
    atexit.register(stop_worker)
    if a.red:
        app.run(host="0.0.0.0", port=a.puerto, debug=False, ssl_context="adhoc")
    else:
        app.run(host="127.0.0.1", port=a.puerto, debug=False)


if __name__ == "__main__":
    main()
