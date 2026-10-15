"""Empresas cliente (aseguradoras): cada siniestro y cada usuario pertenecen a una.

Reglas (Ley 21.719: cada aseguradora es responsable de sus datos y Zelekpress los trata por encargo):
  - El administrador (Zelekpress) ve todas las empresas y es el único que las crea.
  - Jefes, analistas e investigadores pertenecen a una empresa y solo ven siniestros de ella.
  - Las redes de fraude se cruzan solo dentro de cada empresa: cada una tiene su propio registro.
  - Un siniestro sin empresa (los anteriores a esta separación) solo lo ve el administrador.

Las empresas viven en la base de datos (tabla empresas); la empresa de cada caso, en su case.json
(y en su cadena de custodia), con copia en el índice de casos.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from evidex.core import db

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")


def all_clients(workdir: Path) -> dict[str, dict]:
    with db.open_db(workdir).read() as con:
        return {r["slug"]: {"nombre": r["nombre"], "creada": r["creada"]}
                for r in con.execute("SELECT * FROM empresas ORDER BY nombre COLLATE NOCASE")}


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
    with db.open_db(workdir).tx() as con:
        row = con.execute("SELECT nombre FROM empresas WHERE slug=?", (slug,)).fetchone()
        if row:
            return None, f"Ya existe la empresa {row['nombre']}."
        con.execute("INSERT INTO empresas VALUES (?,?,?)", (slug, nombre, db.now()))
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
    db.index_case(case.root.parent, case.root.name, cliente=slug)


def registry(workdir: Path, slug: str | None) -> Path:
    """Registro de siniestros para cruzar redes: uno por empresa. Sin empresa: el registro histórico."""
    if not slug:
        return Path(workdir) / "registro.jsonl"
    d = Path(workdir) / "registros"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{slug}.jsonl"
