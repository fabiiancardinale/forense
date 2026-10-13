"""Empresas cliente (aseguradoras): cada siniestro y cada usuario pertenecen a una.

Reglas (Ley 21.719: cada aseguradora es responsable de sus datos y Zelekpress los trata por encargo):
  - El administrador (Zelekpress) ve todas las empresas y es el único que las crea.
  - Jefes, analistas e investigadores pertenecen a una empresa y solo ven siniestros de ella.
  - Las redes de fraude se cruzan solo dentro de cada empresa: cada una tiene su propio registro.
  - Un siniestro sin empresa (los anteriores a esta separación) solo lo ve el administrador.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from evidex.core.storage import atomic_json

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")


def _path(workdir: Path) -> Path:
    return Path(workdir) / "clientes.json"


def all_clients(workdir: Path) -> dict[str, dict]:
    try:
        data = json.loads(_path(workdir).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def name_of(workdir: Path, slug: str | None) -> str:
    if not slug:
        return "Sin empresa"
    return (all_clients(workdir).get(slug) or {}).get("nombre") or slug


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:30]


def add(workdir: Path, nombre: str) -> tuple[str | None, str | None]:
    """Crea una empresa cliente. Devuelve (slug, error)."""
    nombre = nombre.strip()[:80]
    slug = slugify(nombre)
    if len(nombre) < 2 or not SLUG.fullmatch(slug or ""):
        return None, "Escriba el nombre de la empresa (al menos 2 letras)."
    data = all_clients(workdir)
    if slug in data:
        return None, f"Ya existe la empresa {data[slug]['nombre']}."
    data[slug] = {"nombre": nombre, "creada": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    atomic_json(_path(workdir), data)
    return slug, None


def of_case(case) -> str | None:
    try:
        return json.loads(case.meta_path.read_text(encoding="utf-8")).get("cliente") or None
    except (OSError, ValueError):
        return None


def set_case(case, slug: str | None, actor: str = "evidex") -> None:
    """Asigna la empresa del caso (queda también en la cadena de custodia)."""
    meta = json.loads(case.meta_path.read_text(encoding="utf-8"))
    if (meta.get("cliente") or None) == (slug or None):
        return
    meta["cliente"] = slug or None
    case.meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    case.ledger.append(actor, "cliente_asignado", slug or "sin empresa", {"cliente": slug})


def registry(workdir: Path, slug: str | None) -> Path:
    """Registro de siniestros para cruzar redes: uno por empresa. Sin empresa: el registro histórico."""
    if not slug:
        return Path(workdir) / "registro.jsonl"
    d = Path(workdir) / "registros"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{slug}.jsonl"
