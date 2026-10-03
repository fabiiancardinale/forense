"""Ledger de custodia: registro append-only con hash encadenado y firma Ed25519.

Cada entrada incluye el hash de la anterior. Alterar, borrar o reordenar cualquier
entrada rompe la cadena. La cabeza de la cadena se firma con Ed25519, de modo que un
tercero (perito contraparte, auditor, tribunal) puede verificar sin confiar en nosotros.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
import os
from evidex.core.storage import atomic_json, serialized
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

_CACHE: dict[str, tuple] = {}     # ruta -> ((ruta, tamaño, mtime), entradas)
GENESIS = "0" * 64


def _canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def entry_hash(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(_canon(body)).hexdigest()


class Ledger:
    def __init__(self, case_dir: Path):
        self.dir = Path(case_dir)
        self.path = self.dir / "ledger.jsonl"
        self.key_path = self.dir / "signing_key.pem"
        self.pub_path = self.dir / "public_key.pem"

    # ---- claves -------------------------------------------------------
    @serialized(lambda self, *a, **kw: self.path)
    def init_keys(self) -> None:
        if self.key_path.exists():
            return
        key = Ed25519PrivateKey.generate()
        self.key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        self.key_path.chmod(0o600)
        self.pub_path.write_bytes(
            key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )

    def _private(self) -> Ed25519PrivateKey:
        return serialization.load_pem_private_key(self.key_path.read_bytes(), password=None)

    # ---- lectura / escritura -----------------------------------------
    @serialized(lambda self, *a, **kw: self.path)
    def entries(self) -> list[dict]:
        """Entradas de la cadena. Se guarda en memoria mientras el archivo no cambie (mismo tamaño y fecha)."""
        try:
            st = self.path.stat()
        except OSError:
            return []
        key = (str(self.path), st.st_size, st.st_mtime_ns)
        hit = _CACHE.get(key[0])
        if hit and hit[0] == key:
            return [{**e, "data": dict(e["data"])} for e in hit[1]]
        items = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        _CACHE[key[0]] = (key, items)
        return [{**e, "data": dict(e["data"])} for e in items]

    @serialized(lambda self, *a, **kw: self.path)
    def append(self, actor: str, action: str, subject: str, data: dict | None = None) -> dict:
        entries = self.entries()
        prev = entries[-1]["hash"] if entries else GENESIS
        entry = {
            "seq": len(entries),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "actor": actor,
            "action": action,
            "subject": subject,
            "data": data or {},
            "prev": prev,
        }
        entry["hash"] = entry_hash(entry)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return entry

    @serialized(lambda self, *a, **kw: self.path)
    def seal(self) -> dict:
        """Firma la cabeza actual de la cadena. Devuelve el sello."""
        entries = self.entries()
        head = entries[-1]["hash"] if entries else GENESIS
        sig = self._private().sign(head.encode())
        seal = {
            "head": head,
            "length": len(entries),
            "signature": base64.b64encode(sig).decode(),
            "sealed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        atomic_json(self.dir / "seal.json", seal)
        return seal


# ---- verificación (usada también por el verificador independiente) ----
def verify_chain(entries: list[dict]) -> tuple[bool, str]:
    prev = GENESIS
    for i, e in enumerate(entries):
        if e.get("seq") != i:
            return False, f"entrada {i}: secuencia alterada (seq={e.get('seq')})"
        if e.get("prev") != prev:
            return False, f"entrada {i}: enlace con la anterior roto"
        if entry_hash(e) != e.get("hash"):
            return False, f"entrada {i}: contenido alterado"
        prev = e["hash"]
    return True, f"cadena íntegra ({len(entries)} entradas)"


def verify_seal(entries: list[dict], seal: dict, public_pem: bytes) -> tuple[bool, str]:
    head = entries[-1]["hash"] if entries else GENESIS
    if seal["head"] != head or seal["length"] != len(entries):
        return False, "el sello no corresponde al estado actual (se agregaron o quitaron entradas)"
    pub = serialization.load_pem_public_key(public_pem)
    assert isinstance(pub, Ed25519PublicKey)
    try:
        pub.verify(base64.b64decode(seal["signature"]), head.encode())
    except InvalidSignature:
        return False, "firma inválida"
    return True, "firma válida"
