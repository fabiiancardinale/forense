"""Casos y evidencia: ingesta con hash, copia inmutable y registro en el ledger."""
from __future__ import annotations

import getpass
import hashlib
import json
import shutil
from pathlib import Path

from veritas.core.ledger import Ledger


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Case:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.ledger = Ledger(self.root)
        self.evidence_dir = self.root / "evidence"
        self.meta_path = self.root / "case.json"

    @classmethod
    def create(cls, root: Path, name: str, analyst: str | None = None, kind: str = "incident") -> "Case":
        c = cls(root)
        c.root.mkdir(parents=True, exist_ok=True)
        c.evidence_dir.mkdir(exist_ok=True)
        c.ledger.init_keys()
        c.meta_path.write_text(json.dumps({"name": name, "kind": kind}, indent=2), encoding="utf-8")
        c.ledger.append(analyst or getpass.getuser(), "case_created", name, {"kind": kind})
        return c

    @property
    def name(self) -> str:
        return json.loads(self.meta_path.read_text(encoding="utf-8"))["name"]

    @property
    def kind(self) -> str:
        return json.loads(self.meta_path.read_text(encoding="utf-8")).get("kind", "incident")

    def add_evidence(self, src: Path, analyst: str | None = None, note: str = "", extra: dict | None = None) -> str:
        src = Path(src)
        digest = sha256_file(src)
        dest = self.evidence_dir / digest
        if not dest.exists():
            shutil.copy2(src, dest)
            dest.chmod(0o444)  # solo lectura
        self.ledger.append(
            analyst or getpass.getuser(),
            "evidence_added",
            digest,
            {"original_name": src.name, "size": src.stat().st_size, "note": note, **(extra or {})},
        )
        return digest

    # ---- archivos agregados por error ---------------------------------------------------------
    # La evidencia nunca se borra: borrar rompería la cadena de custodia y permitiría hacer desaparecer
    # una foto incómoda. Un archivo agregado por error se "quita del análisis": queda guardado y
    # registrado (quién, cuándo y por qué), pero ya no se analiza ni aparece en el informe. Se puede restaurar.
    def excluded(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for e in self.ledger.entries():
            if e["action"] == "evidence_excluded":
                out[e["subject"]] = e
            elif e["action"] == "evidence_restored":
                out.pop(e["subject"], None)
        return out

    def active_evidence(self) -> list[dict]:
        ex = self.excluded()
        return [e for e in self.ledger.entries() if e["action"] == "evidence_added" and e["subject"] not in ex]

    def exclude_evidence(self, digest: str, actor: str, reason: str) -> None:
        self.ledger.append(actor, "evidence_excluded", digest, {"reason": reason})

    def restore_evidence(self, digest: str, actor: str) -> None:
        self.ledger.append(actor, "evidence_restored", digest, {})

    def verify_evidence(self) -> tuple[bool, list[str]]:
        """Recalcula el hash de cada archivo y lo compara con lo registrado."""
        problems = []
        for e in self.ledger.entries():
            if e["action"] != "evidence_added":
                continue
            f = self.evidence_dir / e["subject"]
            if not f.exists():
                problems.append(f"falta el archivo {e['subject'][:12]}… ({e['data']['original_name']})")
            elif sha256_file(f) != e["subject"]:
                problems.append(f"hash no coincide: {e['data']['original_name']}")
        return (not problems), problems
