"""Durable private contact notes, separate from expiring media cache."""
import json
from pathlib import Path
import sqlite3
import time
from contextlib import contextmanager

class Conflict(Exception):
    pass

class Workspace:
    def __init__(self, root):
        self.root = Path(root) if root else None

    @contextmanager
    def db(self):
        if self.root is None:
            raise OSError('Durable storage is not configured')
        self.root.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.root / 'workspace.sqlite', timeout=10)
        try:
            db.execute('CREATE TABLE IF NOT EXISTS contacts (key TEXT PRIMARY KEY, notes TEXT NOT NULL, labels TEXT NOT NULL, revision INTEGER NOT NULL, updated REAL NOT NULL)')
            with db:
                yield db
        finally:
            db.close()

    def get(self, key):
        with self.db() as db:
            row = db.execute('SELECT notes,labels,revision,updated FROM contacts WHERE key=?', (key,)).fetchone()
        return {'key': key, 'notes': row[0] if row else '', 'labels': json.loads(row[1]) if row else [], 'revision': row[2] if row else 0, 'updated': row[3] if row else None}

    def summary(self):
        with self.db() as db:
            return {key: {'labels': json.loads(labels), 'hasNotes': bool(notes), 'revision': revision} for key, notes, labels, revision in db.execute('SELECT key,notes,labels,revision FROM contacts')}

    def save(self, key, notes, labels, revision):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision FROM contacts WHERE key=?', (key,)).fetchone()
            actual = row[0] if row else 0
            if revision != actual:
                raise Conflict()
            updated = time.time()
            db.execute('INSERT OR REPLACE INTO contacts VALUES (?,?,?,?,?)', (key, notes, json.dumps(labels, ensure_ascii=False), actual + 1, updated))
        return {'key': key, 'notes': notes, 'labels': labels, 'revision': actual + 1, 'updated': updated}
