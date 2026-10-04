"""Atomic files and reentrant, cross-process locks for a single-host deployment."""
from __future__ import annotations
import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

_guard = threading.Lock()
_locks = {}
_local = threading.local()

@contextmanager
def locked(path: Path, timeout: float = 15):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path)
    with _guard:
        lock = _locks.setdefault(key, threading.RLock())
    if not lock.acquire(timeout=timeout):
        raise TimeoutError('Almacenamiento ocupado; reintente.')
    held = getattr(_local, 'held', None)
    if held is None:
        held = _local.held = set()
    fd = None
    try:
        if key in held:
            yield
            return
        fd = os.open(str(path) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
        if os.fstat(fd).st_size == 0:
            os.write(fd, b'0')
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise TimeoutError('Almacenamiento ocupado; reintente.')
                time.sleep(.02)
        held.add(key)
        try:
            yield
        finally:
            held.remove(key)
            if os.name == 'nt':
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        if fd is not None:
            os.close(fd)
        lock.release()


def serialized(path_for):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            path = path_for(*args, **kwargs)
            if path is None:
                return fn(*args, **kwargs)
            with locked(path):
                return fn(*args, **kwargs)
        return wrapped
    return decorate


def atomic_bytes(path: Path, data: bytes, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def atomic_json(path: Path, data):
    atomic_bytes(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode())
