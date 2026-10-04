"""SQLite queue. Every job has an owner; workers claim jobs transactionally."""
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

class QueueFull(ValueError):
    pass

class Jobs:
    def __init__(self, workdir):
        self.root = Path(workdir) / 'analisis'
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / 'jobs.sqlite3'
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
                sha256 TEXT NOT NULL, size INTEGER NOT NULL, created REAL NOT NULL,
                status TEXT NOT NULL, started REAL, finished REAL, lease TEXT,
                attempt INTEGER NOT NULL DEFAULT 0, result TEXT, consent INTEGER NOT NULL DEFAULT 0,
                request_key TEXT NOT NULL, UNIQUE(owner, request_key));
                CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner, created);
                CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created);''')
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def add(self, job_id, owner, name, digest, size, request_key, consent=False):
        now = time.time()
        with self.db() as db:
            old = db.execute('SELECT * FROM jobs WHERE owner=? AND request_key=?', (owner, request_key)).fetchone()
            if old:
                if old['sha256'] != digest:
                    raise ValueError('Clave de solicitud reutilizada con otro archivo.')
                return old['id']
            pending = db.execute("SELECT count(*) FROM jobs WHERE owner=? AND status IN ('queued','running')", (owner,)).fetchone()[0]
            recent = db.execute('SELECT count(*) FROM jobs WHERE owner=? AND created>?', (owner, now-3600)).fetchone()[0]
            total = db.execute('SELECT coalesce(sum(size),0) FROM jobs WHERE owner=?', (owner,)).fetchone()[0]
            if pending >= 10 or recent >= 30 or total + size > 1_000_000_000:
                raise QueueFull('Se alcanzó la cuota: 10 pendientes, 30 archivos/hora o 1 GB almacenado. Contacte al administrador.')
            db.execute('INSERT INTO jobs(id,owner,name,sha256,size,created,status,consent,request_key) VALUES (?,?,?,?,?,?,?,?,?)',
                       (job_id, owner, name, digest, size, now, 'queued', int(consent), request_key))
        return job_id

    def get(self, job_id, owner):
        with self.db() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=? AND owner=?', (job_id, owner)).fetchone()
        return self.decode(row)

    def list(self, owner):
        with self.db() as db:
            rows = db.execute('SELECT * FROM jobs WHERE owner=? ORDER BY created DESC LIMIT 100', (owner,)).fetchall()
        return [self.decode(r) for r in rows]

    @staticmethod
    def decode(row):
        if not row:
            return None
        out = dict(row)
        out['result'] = json.loads(out['result']) if out['result'] else None
        return out

    def claim(self):
        now = time.time()
        with self.db() as db:
            # A killed supervisor cannot leave jobs running forever; no automatic
            # repeats of a possibly billable external request.
            db.execute("UPDATE jobs SET status='failed', result=?, finished=? WHERE status='running' AND started<?",
                       (json.dumps({'verdict':'inconclusive','summary':'El worker se interrumpió. Reintente el análisis.'}), now, now-240))
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:
                return None
            lease = secrets.token_hex(16)
            db.execute("UPDATE jobs SET status='running', started=?, lease=?, attempt=attempt+1 WHERE id=?", (now,lease,row['id']))
        result = dict(row); result['lease'] = lease
        return result

    def finish(self, job_id, lease, status, result):
        if status not in ('completed','partial','failed','rejected'):
            raise ValueError('Invalid terminal state')
        with self.db() as db:
            return db.execute("UPDATE jobs SET status=?, result=?, finished=? WHERE id=? AND lease=? AND status='running'",
                              (status,json.dumps(result,ensure_ascii=False,allow_nan=False),time.time(),job_id,lease)).rowcount == 1

    def retry(self, job_id, owner):
        with self.db() as db:
            row = db.execute('SELECT status, attempt FROM jobs WHERE id=? AND owner=?',(job_id,owner)).fetchone()
            if not row or row['status'] != 'failed' or row['attempt'] >= 3:
                return False
            pending = db.execute("SELECT count(*) FROM jobs WHERE owner=? AND status IN ('queued','running')",(owner,)).fetchone()[0]
            if pending >= 10:
                raise QueueFull('Ya hay 10 análisis pendientes.')
            db.execute("UPDATE jobs SET status='queued', lease=NULL, result=NULL WHERE id=? AND owner=?",(job_id,owner))
            return True
