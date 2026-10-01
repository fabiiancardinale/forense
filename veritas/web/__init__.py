"""Interfaz web local de Veritas.

Mapa del paquete:
  app.py          fábrica de la aplicación, seguridad (sesión, red) y registro de secciones
  common.py       funciones compartidas por las vistas (casos, usuario actual, resúmenes)
  icons.py        íconos SVG
  views/          una sección por archivo (blueprint):
      panel.py           inicio
      claims.py          siniestros: cola, registro, ficha del caso, evidencia, decisión
      portfolio.py       redes, métricas, importación del historial, Excel
      investigations.py  expedientes de peritos y auditoría de informes
      portal.py          portal público del asegurado (/c/<enlace>)
      tools.py           revisar una foto suelta
      auth.py, admin.py  ingreso, usuarios y configuración
  templates/      plantillas HTML, una carpeta por sección
  static/         estilos (app.css, portal.css, login.css)
"""
from veritas.web.app import create_app

__all__ = ["create_app"]
