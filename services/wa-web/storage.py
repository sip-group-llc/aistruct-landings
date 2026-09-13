"""Bounded private disk cache. No network access and no credentials stored."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager


class PersistentCache:
    def __init__(self, root, scope, max_bytes=2 * 1024**3, ttl=7 * 86400):
        self.root = Path(root) / hashlib.sha256(scope.encode()).hexdigest()[:24] if root else None
        self.scope = scope
        self.max_bytes = max_bytes
        self.ttl = ttl
        self.lock = threading.RLock()
        self._last_sweep = None

    def _remove(self, db, key, kind):
        if kind == 'media' and len(key) == 64 and all(c in '0123456789abcdef' for c in key):
            (self.root / (key + '.bin')).unlink(missing_ok=True)
        db.execute('DELETE FROM entries WHERE key=?', (key,))

    def _sweep(self, db):
        now = time.time()
        for key, kind in db.execute('SELECT key,kind FROM entries WHERE created<=?', (now - self.ttl,)).fetchall():
            self._remove(db, key, kind)
        known = {row[0] + '.bin' for row in db.execute("SELECT key FROM entries WHERE kind='media'")}
        for file in self.root.iterdir():
            generated = (file.suffix == '.bin' and len(file.stem) == 64) or (file.suffix == '.tmp' and len(file.stem) == 32)
            if generated and all(c in '0123456789abcdef' for c in file.stem) and file.name not in known and now - file.stat().st_mtime > 3600:
                file.unlink(missing_ok=True)

    def key(self, kind, identity):
        return hashlib.sha256((self.scope + '\0' + kind + '\0' + identity).encode()).hexdigest()

    @contextmanager
    def _db(self):
        self.root.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.root / 'cache.sqlite', timeout=10)
        try:
            db.execute('CREATE TABLE IF NOT EXISTS entries (key TEXT PRIMARY KEY, kind TEXT, payload TEXT, size INTEGER, created REAL, touched REAL)')
            with db:
                db.execute('BEGIN IMMEDIATE')
                if self._last_sweep is None or time.monotonic() - self._last_sweep > 3600:
                    self._sweep(db)
                    self._last_sweep = time.monotonic()
                yield db
        finally:
            db.close()

    def get(self, kind, identity):
        if not self.root:
            return None
        key = self.key(kind, identity)
        with self.lock:
            try:
                with self._db() as db:
                    row = db.execute('SELECT payload,created FROM entries WHERE key=?', (key,)).fetchone()
                    if not row:
                        return None
                    if time.time() - row[1] >= self.ttl:
                        self._remove(db, key, kind)
                        return None
                    value = json.loads(row[0])
                    if kind == 'media':
                        value = (value['mime'], (self.root / (key + '.bin')).read_bytes())
                    db.execute('UPDATE entries SET touched=? WHERE key=?', (time.time(), key))
                    return value
            except (OSError, sqlite3.Error, ValueError, KeyError):
                return None

    def put(self, kind, identity, value):
        if not self.root:
            return False
        key = self.key(kind, identity)
        raw = value[1] if kind == 'media' else None
        payload = json.dumps({'mime': value[0]} if kind == 'media' else value, ensure_ascii=False)
        size = len(raw) if raw is not None else len(payload.encode())
        if size > min(self.max_bytes, 50 * 1024**2):
            return False
        temporary = None
        with self.lock:
            try:
                with self._db() as db:
                    if raw is not None:
                        temporary = self.root / (uuid.uuid4().hex + '.tmp')
                        temporary.write_bytes(raw)
                        os.replace(temporary, self.root / (key + '.bin'))
                    now = time.time()
                    db.execute('INSERT OR REPLACE INTO entries VALUES (?,?,?,?,?,?)', (key, kind, payload, size, now, now))
                    rows = db.execute('SELECT key,kind,size,created FROM entries ORDER BY touched DESC').fetchall()
                    used = 0
                    for old_key, old_kind, old_size, created in rows:
                        if now - created >= self.ttl or used + old_size > self.max_bytes:
                            self._remove(db, old_key, old_kind)
                        else:
                            used += old_size
                    return True
            except (OSError, sqlite3.Error, ValueError):
                return False
            finally:
                if temporary:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass

    def stats(self):
        if not self.root:
            return {'enabled': False}
        with self.lock:
            try:
                with self._db() as db:
                    count, size = db.execute('SELECT COUNT(*),COALESCE(SUM(size),0) FROM entries').fetchone()
                return {'enabled': True, 'entries': count, 'bytes': size, 'limitBytes': self.max_bytes}
            except (OSError, sqlite3.Error):
                return {'enabled': False}
