"""Línea de tiempo unificada: normaliza eventos de varias fuentes en SQLite.

Cada evento recibe un ID estable y citable: "<hash-evidencia[:8]>:<n° de línea>".
Ese ID es la base del asistente verificable: toda afirmación debe apuntar a uno.
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  id TEXT PRIMARY KEY, ts TEXT NOT NULL, host TEXT, source TEXT,
  event_id INTEGER, user TEXT, message TEXT, raw TEXT
);
CREATE INDEX IF NOT EXISTS idx_ts ON events(ts);
"""


def _iso(value) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    s = str(value).replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1]
    dt = datetime.fromisoformat(s.split("+")[0])
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_jsonl(path: Path):
    """Un evento JSON por línea. Campos: ts, host, source, event_id, user, message."""
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            d = json.loads(line)
            yield n, d


def parse_csv(path: Path):
    with Path(path).open(newline="", encoding="utf-8") as f:
        for n, d in enumerate(csv.DictReader(f), 1):
            yield n, d


_AUTH = re.compile(r"^(\w{3}\s+\d+\s[\d:]+)\s(\S+)\s(\S+?)(?:\[\d+\])?:\s(.*)$")


def parse_authlog(path: Path, year: int = 2026):
    """Formato syslog clásico de Linux (/var/log/auth.log)."""
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        m = _AUTH.match(line)
        if not m:
            continue
        ts = datetime.strptime(f"{year} {m.group(1)}", "%Y %b %d %H:%M:%S")
        yield n, {"ts": ts.isoformat(), "host": m.group(2), "source": m.group(3), "message": m.group(4)}


def parse_evtx(path: Path):
    """Registros de eventos de Windows (.evtx). Requiere `pip install python-evtx`."""
    from xml.etree import ElementTree as ET

    import Evtx.Evtx as evtx  # type: ignore

    ns = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}
    with evtx.Evtx(str(path)) as log:
        for n, rec in enumerate(log.records(), 1):
            x = ET.fromstring(rec.xml())
            sysd = x.find("e:System", ns)
            data = {d.get("Name"): (d.text or "") for d in x.findall(".//e:EventData/e:Data", ns)}
            yield n, {
                "ts": sysd.find("e:TimeCreated", ns).get("SystemTime"),
                "host": sysd.find("e:Computer", ns).text,
                "source": sysd.find("e:Channel", ns).text,
                "event_id": int(sysd.find("e:EventID", ns).text),
                "user": data.get("TargetUserName") or data.get("SubjectUserName"),
                "message": json.dumps(data, ensure_ascii=False),
            }


PARSERS = {".jsonl": parse_jsonl, ".csv": parse_csv, ".log": parse_authlog, ".evtx": parse_evtx}


class Timeline:
    def __init__(self, db_path: Path, fresh: bool = False):
        self.db = sqlite3.connect(str(db_path), timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        if fresh:
            # se vacía en vez de borrar el archivo: en Windows no se puede borrar un archivo
            # que otro proceso tiene abierto (antivirus, indexador, otra pestaña analizando)
            self.db.execute("DELETE FROM events")
            self.db.commit()

    def ingest(self, path: Path, digest: str, original_name: str) -> int:
        parser = PARSERS.get(Path(original_name).suffix.lower())
        if not parser:
            raise ValueError(f"formato no soportado: {original_name}")
        count = 0
        for n, d in parser(path):
            eid = d.get("event_id")
            self.db.execute(
                "INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?,?)",
                (
                    f"{digest[:8]}:{n}",
                    _iso(d["ts"]),
                    d.get("host"),
                    d.get("source"),
                    int(eid) if eid not in (None, "") else None,
                    d.get("user"),
                    d.get("message", ""),
                    json.dumps(d, ensure_ascii=False),
                ),
            )
            count += 1
        self.db.commit()
        return count

    def add_event(self, eid, ts, host, source, event_id, user, message) -> None:
        self.db.execute("INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?,?)",
                        (eid, ts, host, source, event_id, user, message, "{}"))
        self.db.commit()

    def add_events(self, rows) -> None:
        """Varios eventos en una sola transacción: (id, ts, host, source, event_id, user, message)."""
        self.db.executemany("INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?,'{}')", list(rows))
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def all(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM events ORDER BY ts, id").fetchall()

    def get(self, event_id: str):
        return self.db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()

    def exists(self, event_id: str) -> bool:
        return self.get(event_id) is not None
