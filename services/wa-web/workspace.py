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
            db.execute('CREATE TABLE IF NOT EXISTS flags (key TEXT PRIMARY KEY, favorite INTEGER NOT NULL, pending INTEGER NOT NULL, revision INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS chat_aliases (alias TEXT PRIMARY KEY, canonical TEXT NOT NULL, updated REAL NOT NULL)')
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
            result = {key: {'labels': json.loads(labels), 'hasNotes': bool(notes), 'revision': revision} for key, notes, labels, revision in db.execute('SELECT key,notes,labels,revision FROM contacts')}
            for key, favorite, pending, revision in db.execute('SELECT key,favorite,pending,revision FROM flags'):
                result.setdefault(key, {'labels': [], 'hasNotes': False, 'revision': 0})['flags'] = {'favorite': bool(favorite), 'pending': bool(pending), 'revision': revision}
            return result

    def import_flags(self, items):
        with self.db() as db:
            for key, flags in items.items():
                db.execute('INSERT OR IGNORE INTO flags VALUES (?,?,?,1)', (key, int(flags.get('favorite', False)), int(flags.get('pending', False))))

    def set_flag(self, key, field, value, revision):
        if field not in ('favorite', 'pending'):
            raise ValueError('Invalid field')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT favorite,pending,revision FROM flags WHERE key=?', (key,)).fetchone() or (0, 0, 0)
            if row[2] != revision:
                raise Conflict()
            flags = {'favorite': bool(row[0]), 'pending': bool(row[1]), 'revision': row[2] + 1}
            flags[field] = value
            db.execute('INSERT OR REPLACE INTO flags VALUES (?,?,?,?)', (key, int(flags['favorite']), int(flags['pending']), flags['revision']))
        return flags

    def chat_aliases(self):
        with self.db() as db:
            return dict(db.execute('SELECT alias,canonical FROM chat_aliases'))

    def learn_chat_aliases(self, pairs):
        updated = time.time()
        with self.db() as db:
            for alias, canonical in pairs:
                db.execute('INSERT OR REPLACE INTO chat_aliases VALUES (?,?,?)', (alias, canonical, updated))

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
