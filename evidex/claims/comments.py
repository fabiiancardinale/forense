"""Comentarios internos del siniestro entre analista, jefe e investigador, con @menciones.

Cada comentario es una entrada de la cadena de custodia del caso (acción "comentario"): queda con
quién y cuándo, encadenada por hash, y no se puede editar ni borrar. Para corregir, se escribe otro.
El informe del caso solo muestra que hubo un comentario, no su texto.

Las @menciones se guardan además en la base de datos (tabla menciones) para mostrarle a cada persona,
en Inicio, lo que le pidieron y aún no ha leído. Solo se puede mencionar a quien puede ver el caso.
"""
from __future__ import annotations

import re
from pathlib import Path

from evidex.core import db

MAX_LEN = 2000
MENTION = re.compile(r"(?<![\w.@])@([a-z0-9][a-z0-9._-]{2,31})", re.IGNORECASE)


def listing(case) -> list[dict]:
    out = []
    for e in case.ledger.entries():
        if e["action"] == "comentario":
            d = e.get("data") or {}
            out.append({"seq": e["seq"], "ts": e["ts"], "autor": d.get("nombre") or e["actor"], "usuario": e["subject"],
                        "texto": d.get("texto", ""), "menciones": d.get("menciones", []), "hash": e["hash"]})
    return out


def count(case) -> int:
    return sum(1 for e in case.ledger.entries() if e["action"] == "comentario")


def can_see(user: dict, case) -> bool:
    """Misma regla que la cola de siniestros, para alguien que no es quien está usando la página."""
    from evidex.accounts import clients, users
    from evidex.claims import assignment
    role = user.get("role")
    if not user.get("active", True) or not users.can(role, "ver_siniestros"):
        return False
    if role == "administrador":
        return True
    if clients.of_case(case) != (user.get("cliente") or None):
        return False
    if users.can(role, "ver_todos"):
        return True
    o = assignment.owner(case)
    return bool(o and o["user"] == user["username"])


def mentionable(store, case, exclude: str = "") -> list[dict]:
    return [{"username": k, "name": u["name"]} for k, u in sorted(store.all().items(), key=lambda kv: kv[1]["name"].lower())
            if k != exclude and can_see({**u, "username": k}, case)]


def add(workdir: Path, case, store, username: str, name: str, texto: str) -> tuple[dict, list[str]]:
    """Registra el comentario. Devuelve (entrada, menciones_ignoradas). ValueError si el texto no sirve."""
    texto = (texto or "").replace("\r\n", "\n").strip()
    if not texto:
        raise ValueError("Escriba el comentario.")
    if len(texto) > MAX_LEN:
        raise ValueError(f"El comentario no puede superar {MAX_LEN} caracteres.")
    allowed = {u["username"] for u in mentionable(store, case, exclude=username)}
    named = list(dict.fromkeys(m.lower() for m in MENTION.findall(texto)))
    ok = [n for n in named if n in allowed]
    ignored = [n for n in named if n not in allowed and n != username]
    entry = case.ledger.append(name or username, "comentario", username, {"texto": texto, "nombre": name, "menciones": ok})
    if ok:
        extracto = " ".join(texto.split())[:160]
        with db.open_db(workdir).tx() as con:
            con.executemany("INSERT OR IGNORE INTO menciones (caso, seq, para, de, de_nombre, extracto, ts) VALUES (?,?,?,?,?,?,?)",
                            [(case.root.name, entry["seq"], n, username, name or username, extracto, entry["ts"]) for n in ok])
    return entry, ignored


def pending(workdir: Path, username: str, limit: int = 20) -> list[dict]:
    with db.open_db(workdir).read() as con:
        return [dict(r) for r in con.execute("SELECT * FROM menciones WHERE para=? AND leida IS NULL ORDER BY ts DESC LIMIT ?",
                                             (username, limit))]


def mark_read(workdir: Path, case_id: str, username: str) -> int:
    with db.open_db(workdir).tx() as con:
        return con.execute("UPDATE menciones SET leida=? WHERE caso=? AND para=? AND leida IS NULL",
                           (db.now(), case_id, username)).rowcount
