"""Rutas fijas del proyecto (carpeta de demos), en un solo lugar."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = PROJECT_ROOT / "demo"
