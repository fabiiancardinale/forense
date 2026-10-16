"""Subida por partes (videos): el navegador manda el archivo en trozos de hasta 8 MB, uno tras otro.

Así un video de cientos de MB pasa por el límite de 26 MB por pedido, y si se corta la señal del celular se
reintenta solo el trozo que falló. Cada subida queda atada a quien la empezó (el caso y el usuario, o el enlace
del portal): nadie más puede agregarle trozos. Las subidas abandonadas se borran a las 24 horas.
"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

from evidex.core.storage import atomic_json, locked

CHUNK_MAX = 8 * 1024 * 1024
UPLOAD_ID = re.compile(r"[0-9a-f]{32}")
STALE_SECONDS = 24 * 3600
FOLDER = "_subidas"


class ChunkError(ValueError):
    pass


def _folder(workdir: Path) -> Path:
    d = Path(workdir) / FOLDER
    d.mkdir(parents=True, exist_ok=True)
    return d


def cleanup(workdir: Path) -> None:
    now = time.time()
    for p in _folder(workdir).glob("*"):
        try:
            if now - p.stat().st_mtime > STALE_SECONDS:
                p.unlink()
        except OSError:
            pass


def receive(workdir: Path, scope: str, form, blob_file, allowed_ext: set[str], max_bytes: int) -> dict:
    """Guarda un trozo. Devuelve {"done": False, "next": n} o {"done": True, "path": Path, "name", "meta"}."""
    uid = (form.get("id") or "").lower()
    if not UPLOAD_ID.fullmatch(uid):
        raise ChunkError("Subida no válida.")
    try:
        n, total, size = int(form.get("n", "")), int(form.get("total", "")), int(form.get("size", ""))
    except ValueError as ex:
        raise ChunkError("Subida no válida.") from ex
    name = Path((form.get("name") or "video").replace("\\", "/")).name[:120] or "video"
    if Path(name).suffix.lower() not in allowed_ext:
        raise ChunkError("Solo se aceptan videos MP4 o MOV.")
    if not 0 < size <= max_bytes:
        raise ChunkError(f"El video es demasiado grande (máximo {max_bytes // 1_000_000} MB).")
    if total != math.ceil(size / CHUNK_MAX) or not 0 <= n < total:
        raise ChunkError("Subida no válida.")
    folder = _folder(workdir)
    meta_p, part = folder / f"{uid}.json", folder / f"{uid}.part"
    with locked(meta_p):
        if n == 0 and not meta_p.exists():
            cleanup(workdir)
            meta = {"scope": scope, "name": name, "size": size, "total": total, "next": 0, "ts": time.time(),
                    "extra": {k: (form.get(k) or "")[:200] for k in ("titulo", "modificado")}}
            part.write_bytes(b"")
        else:
            try:
                meta = json.loads(meta_p.read_text(encoding="utf-8"))
            except (OSError, ValueError) as ex:
                raise ChunkError("La subida venció. Elija el video de nuevo.") from ex
            if meta["scope"] != scope or meta["name"] != name or meta["size"] != size or meta["total"] != total:
                raise ChunkError("Subida no válida.")
        if n < meta["next"]:
            return {"done": False, "next": meta["next"]}          # trozo repetido (reintento): ya estaba
        if n > meta["next"]:
            raise ChunkError("Falta una parte del video. Intente de nuevo.")
        data = blob_file.read(CHUNK_MAX + 1) if blob_file else b""
        expected = CHUNK_MAX if n < total - 1 else size - CHUNK_MAX * (total - 1)
        if len(data) != expected:
            raise ChunkError("Una parte del video llegó incompleta. Intente de nuevo.")
        with open(part, "ab") as f:
            f.write(data)
        meta["next"] = n + 1
        atomic_json(meta_p, meta)
        if meta["next"] < total:
            return {"done": False, "next": meta["next"]}
        if part.stat().st_size != size:
            raise ChunkError("El video llegó incompleto. Intente de nuevo.")
        return {"done": True, "path": part, "name": name, "meta": meta, "meta_path": meta_p}


def finish(result: dict) -> None:
    """Borra los archivos de la subida (después de guardar el video en el caso, o si se rechazó)."""
    for k in ("path", "meta_path"):
        try:
            Path(result[k]).unlink()
        except (KeyError, OSError):
            pass
