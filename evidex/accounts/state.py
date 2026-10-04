"""Durable rate limits and revocable sessions. No passwords or raw tokens in this DB."""
import hashlib
import secrets
import sqlite3
import time
from contextlib import contextmanager

class AuthState:
    def __init__(self, path):
        self.path = path
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS attempts (bucket TEXT, ts REAL);
                CREATE INDEX IF NOT EXISTS attempts_bucket ON attempts(bucket, ts);
                CREATE TABLE IF NOT EXISTS sessions
                (digest TEXT PRIMARY KEY, username TEXT, version TEXT, created REAL, seen REAL);
            ''')
        path.chmod(0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.execute('PRAGMA busy_timeout=15000')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def check(self, username, ip, verify):
        now = time.time()
        bucket = hashlib.sha256(('user:' + username).encode()).hexdigest()
        origin = hashlib.sha256(('ip:' + ip).encode()).hexdigest()
        with self.connection() as db:
            db.execute('DELETE FROM attempts WHERE ts < ?', (now - 300,))
            for key, maximum in [(bucket, 5), (origin, 30)]:
                if db.execute('SELECT count(*) FROM attempts WHERE bucket=?', (key,)).fetchone()[0] >= maximum:
                    return None, 'Demasiados intentos fallidos. Espere 5 minutos e intente de nuevo.'
            user = verify()
            if user:
                db.execute('DELETE FROM attempts WHERE bucket=?', (bucket,))
                return user, None
            db.executemany('INSERT INTO attempts VALUES (?,?)', [(bucket, now), (origin, now)])
            return None, 'Usuario o contraseña incorrectos.'

    def issue(self, user):
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.connection() as db:
            db.execute('DELETE FROM sessions WHERE created < ?', (now - 28800,))
            db.execute('INSERT INTO sessions VALUES (?,?,?,?,?)',
                       (self.digest(token), user['username'], user.get('auth_version', ''), now, now))
        return token

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def valid(self, token, user, idle=1800, absolute=28800):
        if not token or not user:
            return False
        now = time.time()
        with self.connection() as db:
            row = db.execute('SELECT username, version, created, seen FROM sessions WHERE digest=?',
                             (self.digest(token),)).fetchone()
            if not row or row[0] != user['username'] or row[1] != user.get('auth_version', '') or now-row[2] > absolute or now-row[3] > idle:
                return False
            db.execute('UPDATE sessions SET seen=? WHERE digest=?', (now, self.digest(token)))
        return True

    def revoke(self, token):
        if token:
            with self.connection() as db:
                db.execute('DELETE FROM sessions WHERE digest=?', (self.digest(token),))
