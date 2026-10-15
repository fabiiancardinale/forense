"""Base de datos de Evidex (SQLite): lo que se relaciona entre sí.

Qué guarda:
  empresas    empresas cliente (aseguradoras)
  usuarios    cuentas, roles, empresa, 2FA (las contraseñas solo como hash)
  firmas      empresas de peritaje
  casos       índice de cada siniestro: empresa y analista asignado
  menciones   @menciones en comentarios internos y si ya se leyeron (el comentario está en la cadena de custodia)

Qué NO guarda: las pruebas, el análisis ni la cadena de custodia. Eso sigue en la carpeta de cada
caso, porque es lo que se entrega como prueba. La asignación de un caso se registra primero en su
cadena de custodia; la tabla `casos` es solo un índice para consultar rápido y se reconstruye
desde las carpetas al arrancar.

Al abrirla por primera vez importa los archivos anteriores (usuarios.json, clientes.json,
empresas.json) y los deja renombrados como *.migrado, sin borrarlos.

Un solo archivo (evidex.sqlite3) en la carpeta de casos. El respaldo usa la copia en caliente de
SQLite (`python -m evidex.core.db respaldar`), no una copia directa del archivo.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

NAME = "evidex.sqlite3"

# Cada cambio de estructura es un paso nuevo al final; nunca se edita uno ya publicado.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE empresas (
        slug     TEXT PRIMARY KEY,
        nombre   TEXT NOT NULL,
        creada   TEXT NOT NULL
    );
    CREATE TABLE usuarios (
        username     TEXT PRIMARY KEY,
        name         TEXT NOT NULL,
        role         TEXT NOT NULL,
        active       INTEGER NOT NULL DEFAULT 1,
        empresa      TEXT NOT NULL DEFAULT '',
        cliente      TEXT REFERENCES empresas(slug),
        pw           TEXT NOT NULL,
        auth_version TEXT NOT NULL,
        created      TEXT NOT NULL,
        totp         TEXT,
        totp_since   TEXT,
        totp_step    INTEGER,
        extra        TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX usuarios_cliente ON usuarios(cliente);
    CREATE TABLE firmas (
        nombre   TEXT PRIMARY KEY COLLATE NOCASE,
        rut      TEXT NOT NULL DEFAULT '',
        contacto TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE casos (
        id               TEXT PRIMARY KEY,
        cliente          TEXT,
        analista         TEXT,
        analista_nombre  TEXT,
        asignado_por     TEXT,
        asignado_ts      TEXT
    );
    CREATE INDEX casos_cliente ON casos(cliente);
    CREATE INDEX casos_analista ON casos(analista);
    CREATE TABLE importados (
        archivo  TEXT PRIMARY KEY,
        ts       TEXT NOT NULL,
        filas    INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE menciones (
        id         INTEGER PRIMARY KEY,
        caso       TEXT NOT NULL,
        seq        INTEGER NOT NULL,
        para       TEXT NOT NULL,
        de         TEXT NOT NULL,
        de_nombre  TEXT NOT NULL,
        extracto   TEXT NOT NULL,
        ts         TEXT NOT NULL,
        leida      TEXT,
        UNIQUE (caso, seq, para)
    );
    CREATE INDEX menciones_para ON menciones(para, leida);
    """,
]


class DatabaseError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Database:
    def __init__(self, workdir: Path):
        self.workdir = Path(workdir)
        self.path = self.workdir / NAME

    def _connect(self) -> sqlite3.Connection:
        if not self.workdir.exists():
            self.workdir.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists()
        try:
            db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout=15000")
            db.execute("PRAGMA foreign_keys=ON")
            if new:
                db.execute("PRAGMA journal_mode=WAL")
                try:
                    os.chmod(self.path, 0o600)
                except OSError:
                    pass
            return db
        except sqlite3.DatabaseError as ex:
            raise DatabaseError("No se puede abrir la base de datos de Evidex.") from ex

    @contextmanager
    def tx(self):
        """Transacción de escritura (bloquea a otros escritores hasta terminar)."""
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.execute("COMMIT")
        except BaseException:
            try:
                db.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            db.close()

    @contextmanager
    def read(self):
        db = self._connect()
        try:
            yield db
        finally:
            db.close()

    def version(self) -> int:
        with self.read() as db:
            return db.execute("PRAGMA user_version").fetchone()[0]

    def migrate(self) -> None:
        try:
            self._migrate()
        except sqlite3.DatabaseError as ex:
            raise DatabaseError("La base de datos de Evidex está dañada. Restaure el respaldo.") from ex

    def _migrate(self) -> None:
        with self.tx() as db:
            current = db.execute("PRAGMA user_version").fetchone()[0]
            if current > len(MIGRATIONS):
                raise DatabaseError("La base de datos es de una versión más nueva de Evidex.")
            for i in range(current, len(MIGRATIONS)):
                for stmt in _statements(MIGRATIONS[i]):
                    db.execute(stmt)
                db.execute(f"PRAGMA user_version={i + 1}")
            _import_legacy(self.workdir, db)
        _rename_imported(self.workdir)

    def backup(self, dest: Path) -> Path:
        """Copia consistente aunque la aplicación esté escribiendo."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        with self.read() as src:
            out = sqlite3.connect(dest)
            try:
                src.backup(out)
            finally:
                out.close()
        os.chmod(dest, 0o600)
        return dest


def _statements(script: str) -> list[str]:
    return [s.strip() for s in script.split(";") if s.strip()]


_opened: dict[str, Database] = {}
_lock = threading.Lock()


def open_db(workdir: Path) -> Database:
    """La base de la carpeta de casos, creada y al día. Se migra una vez por proceso."""
    key = str(Path(workdir).resolve())
    with _lock:
        d = _opened.get(key)
        if d is None or not d.path.exists():
            d = Database(workdir)
            d.migrate()
            _opened[key] = d
        return d


def forget(workdir: Path) -> None:
    """Olvida la base abierta (para pruebas que la borran o reemplazan)."""
    with _lock:
        _opened.pop(str(Path(workdir).resolve()), None)


# ---- importación única de los archivos anteriores ------------------------------------------
LEGACY = ("clientes.json", "usuarios.json", "empresas.json")      # en este orden (usuarios apunta a empresas)


def _import_legacy(workdir: Path, db: sqlite3.Connection) -> None:
    for name in LEGACY:
        path = workdir / name
        if not path.exists() or db.execute("SELECT 1 FROM importados WHERE archivo=?", (name,)).fetchone():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as ex:
            raise DatabaseError(f"No se pudo leer {name} para pasarlo a la base de datos. Restaure el respaldo.") from ex
        n = {"clientes.json": _import_clients, "usuarios.json": _import_users, "empresas.json": _import_firms}[name](db, data)
        db.execute("INSERT INTO importados VALUES (?,?,?)", (name, now(), n))


def _import_clients(db, data) -> int:
    if not isinstance(data, dict):
        raise DatabaseError("clientes.json no tiene el formato esperado.")
    for slug, c in data.items():
        db.execute("INSERT OR IGNORE INTO empresas VALUES (?,?,?)", (slug, c.get("nombre") or slug, c.get("creada") or now()))
    return len(data)


USER_COLS = ("name", "role", "active", "empresa", "cliente", "pw", "auth_version", "created", "totp", "totp_since", "totp_step")


def _import_users(db, data) -> int:
    if not isinstance(data, dict) or not data:
        raise DatabaseError("usuarios.json está vacío o dañado.")
    for username, u in data.items():
        if not isinstance(u, dict) or not isinstance(u.get("pw"), str):
            raise DatabaseError(f"usuarios.json: el usuario {username} está dañado.")
        cliente = u.get("cliente") or None
        if cliente and not db.execute("SELECT 1 FROM empresas WHERE slug=?", (cliente,)).fetchone():
            db.execute("INSERT INTO empresas VALUES (?,?,?)", (cliente, cliente, now()))
        extra = {k: v for k, v in u.items() if k not in USER_COLS}
        db.execute("INSERT OR IGNORE INTO usuarios (username, name, role, active, empresa, cliente, pw, auth_version,"
                   " created, totp, totp_since, totp_step, extra) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (username, u.get("name") or username, u.get("role") or "", 1 if u.get("active", True) else 0,
                    u.get("empresa") or "", cliente, u["pw"], u.get("auth_version") or os.urandom(16).hex(),
                    u.get("created") or now(), u.get("totp"), u.get("totp_since"), u.get("totp_step"),
                    json.dumps(extra, ensure_ascii=False)))
    return len(data)


def _import_firms(db, data) -> int:
    if not isinstance(data, list):
        raise DatabaseError("empresas.json no tiene el formato esperado.")
    for f in data:
        db.execute("INSERT OR IGNORE INTO firmas VALUES (?,?,?)", (f.get("nombre", ""), f.get("rut", ""), f.get("contacto", "")))
    return len(data)


def _rename_imported(workdir: Path) -> None:
    """Deja los archivos anteriores como respaldo (*.migrado) para que nadie los edite creyendo que valen."""
    for name in LEGACY:
        p = workdir / name
        if p.exists():
            target = workdir / f"{name}.migrado"
            n = 2
            while target.exists():
                target, n = workdir / f"{name}.migrado{n}", n + 1
            try:
                p.rename(target)
            except FileNotFoundError:
                pass                        # otro proceso ya lo renombró


# ---- índice de casos ----------------------------------------------------------------------------
def index_case(workdir: Path, case_id: str, *, cliente=..., owner=...) -> None:
    """Actualiza el índice de un caso. `owner` es el dict de assignment.owner() o None."""
    sets, vals = [], []
    if cliente is not ...:
        sets.append("cliente=?")
        vals.append(cliente or None)
    if owner is not ...:
        o = owner or {}
        sets += ["analista=?", "analista_nombre=?", "asignado_por=?", "asignado_ts=?"]
        vals += [o.get("user"), o.get("name"), o.get("by"), o.get("ts")]
    if not sets:
        return
    with open_db(workdir).tx() as db:
        db.execute("INSERT OR IGNORE INTO casos (id) VALUES (?)", (case_id,))
        db.execute(f"UPDATE casos SET {', '.join(sets)} WHERE id=?", (*vals, case_id))


def reindex_cases(workdir: Path) -> int:
    """Reconstruye el índice desde las carpetas (la fuente de verdad es la cadena de custodia)."""
    from evidex.accounts import clients
    from evidex.claims import assignment
    from evidex.core.case import Case
    rows = []
    for d in sorted(Path(workdir).iterdir()) if Path(workdir).exists() else []:
        if not (d / "case.json").exists() or not (d / "ledger.jsonl").exists():
            continue
        try:
            case = Case(d)
            o = assignment.owner(case) or {}
            rows.append((d.name, clients.of_case(case), o.get("user"), o.get("name"), o.get("by"), o.get("ts")))
        except Exception:               # una carpeta dañada no impide arrancar; se ve en el caso mismo
            continue
    with open_db(workdir).tx() as db:
        db.execute("DELETE FROM casos")
        db.executemany("INSERT INTO casos VALUES (?,?,?,?,?,?)", rows)
    return len(rows)


def cases(workdir: Path, cliente=..., analista=...) -> list[dict]:
    q, vals = "SELECT * FROM casos WHERE 1=1", []
    if cliente is not ...:
        q += " AND cliente IS ?"
        vals.append(cliente or None)
    if analista is not ...:
        q += " AND analista IS ?"
        vals.append(analista)
    with open_db(workdir).read() as db:
        return [dict(r) for r in db.execute(q + " ORDER BY id", vals)]


def main(argv=None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) == 3 and argv[0] == "respaldar":
        print(open_db(Path(argv[1])).backup(Path(argv[2])))
    elif len(argv) == 2 and argv[0] == "reindexar":
        print(f"{reindex_cases(Path(argv[1]))} casos indexados")
    else:
        sys.exit("Uso: python -m evidex.core.db respaldar <carpeta-casos> <destino.sqlite3> | reindexar <carpeta-casos>")


if __name__ == "__main__":
    main()
