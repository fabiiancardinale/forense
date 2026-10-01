"""Siniestros (blueprint "claims").

  queue.py       cola de trabajo, registro de un siniestro nuevo y carga del ejemplo
  case.py        ficha del caso por pestañas, informe, verificación, paquete y decisión
  evidence.py    archivos del caso: agregar, ver, quitar del análisis, restaurar, versiones de PDF
  derivation.py  analista responsable (reasignar) y derivación de entrevistas a un perito
  portal_link.py crear el enlace del portal para el asegurado
"""
from flask import Blueprint

bp = Blueprint("claims", __name__)

from veritas.web.views.claims import case, derivation, evidence, portal_link, queue  # noqa: E402,F401  (registran rutas)
