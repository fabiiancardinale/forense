"""Casos y evidencia: ingesta con hash, copia inmutable y registro en el ledger."""
from __future__ import annotations

import getpass
import hashlib
import json
import shutil
from pathlib import Path

from evidex.core.ledger import Ledger


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
        """Archivos fuera del análisis: quitados (se pueden restaurar) y eliminados definitivamente."""
        out: dict[str, dict] = {}
        for e in self.ledger.entries():
            if e["action"] in ("evidence_excluded", "evidence_purged"):
                out[e["subject"]] = e
            elif e["action"] == "evidence_restored" and out.get(e["subject"], {}).get("action") != "evidence_purged":
                out.pop(e["subject"], None)
        return out

    def purged(self) -> dict[str, dict]:
        return {e["subject"]: e for e in self.ledger.entries() if e["action"] == "evidence_purged"}

    def active_evidence(self) -> list[dict]:
        ex = self.excluded()
        return [e for e in self.ledger.entries() if e["action"] == "evidence_added" and e["subject"] not in ex]

    def exclude_evidence(self, digest: str, actor: str, reason: str) -> None:
        self.ledger.append(actor, "evidence_excluded", digest, {"reason": reason})

    def restore_evidence(self, digest: str, actor: str) -> None:
        if digest in self.purged():
            raise ValueError("El archivo se eliminó definitivamente: no se puede restaurar.")
        self.ledger.append(actor, "evidence_restored", digest, {})

    # ---- eliminación definitiva (datos de prueba, pedido del asegurado, plazo de conservación cumplido) ----
    # Solo un archivo ya quitado del análisis. Primero se anota en la cadena (quién, cuándo, por qué, nombre y
    # huella del archivo) y después se borra: la cadena sigue íntegra y queda constancia de que existió.
    def purge_evidence(self, digest: str, actor: str, reason: str) -> str:
        added = next((e for e in self.ledger.entries() if e["action"] == "evidence_added" and e["subject"] == digest), None)
        if added is None:
            raise KeyError("El archivo no es parte de este caso.")
        if digest in self.purged():
            return added["data"]["original_name"]
        if digest not in self.excluded():
            raise ValueError("Primero hay que quitar el archivo del análisis.")
        if not reason.strip():
            raise ValueError("Indique el motivo.")
        name = added["data"]["original_name"]
        self.ledger.append(actor, "evidence_purged", digest, {"reason": reason.strip(), "original_name": name})
        (self.evidence_dir / digest).unlink(missing_ok=True)
        for cache in ("analisis_imagen.json", "analisis_pares.json"):      # lo calculado a partir del archivo
            path = self.root / cache
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            def limpio(d):
                return {k: v for k, v in d.items() if digest not in k} if isinstance(d, dict) else d
            data = limpio(data)
            if isinstance(data.get("pairs"), dict):
                data["pairs"] = limpio(data["pairs"])
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return name

    def verify_evidence(self) -> tuple[bool, list[str]]:
        """Recalcula el hash de cada archivo y lo compara con lo registrado."""
        problems = []
        purged = self.purged()
        for e in self.ledger.entries():
            if e["action"] != "evidence_added" or e["subject"] in purged:
                continue
            f = self.evidence_dir / e["subject"]
            if not f.exists():
                problems.append(f"falta el archivo {e['subject'][:12]}… ({e['data']['original_name']})")
            elif sha256_file(f) != e["subject"]:
                problems.append(f"hash no coincide: {e['data']['original_name']}")
        return (not problems), problems
