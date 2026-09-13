"""Opt-in Web Push with durable subscriptions, delivery checkpoints and read receipts."""
import base64
import json
import sqlite3
import time
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit, quote

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import webpush, WebPushException
from py_vapid import Vapid


def validate_subscription(value):
    if not isinstance(value, dict):
        raise ValueError('Inscrição inválida')
    endpoint = str(value.get('endpoint', ''))
    url = urlsplit(endpoint)
    host = url.hostname or ''
    allowed = host in ('fcm.googleapis.com', 'updates.push.services.mozilla.com', 'web.push.apple.com') or host.endswith('.notify.windows.com')
    if not allowed or url.scheme != 'https' or url.port not in (None, 443) or url.username or url.password or url.fragment or len(endpoint) > 4096:
        raise ValueError('Serviço de notificações não suportado')
    keys = value.get('keys') or {}
    try:
        raw = {k: base64.urlsafe_b64decode(str(keys[k]) + '=' * (-len(str(keys[k])) % 4)) for k in ('p256dh', 'auth')}
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw['p256dh'])
        if len(raw['auth']) != 16:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ValueError('Chaves de notificação inválidas') from None
    return {'endpoint': endpoint, 'keys': {k: keys[k] for k in ('p256dh', 'auth')}}


class PushStore:
    def __init__(self, root, owner):
        self.root = Path(root) if root else None
        self.owner = sha256(owner.encode()).hexdigest()
        self.last_error = None

    @contextmanager
    def db(self):
        if not self.root:
            raise OSError('Armazenamento persistente indisponível')
        self.root.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.root / 'notifications.sqlite', timeout=10)
        try:
            db.executescript('''CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS subscriptions (id TEXT PRIMARY KEY,owner TEXT,data TEXT,since REAL);
            CREATE TABLE IF NOT EXISTS delivered (subscription TEXT,message TEXT,ts REAL,PRIMARY KEY(subscription,message));
            CREATE TABLE IF NOT EXISTS reads (jid TEXT,mid TEXT,ts REAL,PRIMARY KEY(jid,mid));''')
            with db:
                yield db
        finally:
            db.close()

    def key(self):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT value FROM config WHERE key='vapid'").fetchone()
            if row:
                return row[0]
            key = ec.generate_private_key(ec.SECP256R1()).private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
            db.execute("INSERT INTO config VALUES ('vapid',?)", (key,))
            return key

    def public_key(self):
        key = serialization.load_pem_private_key(self.key().encode(), password=None)
        return base64.urlsafe_b64encode(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).decode().rstrip('=')

    def subscribe(self, value):
        value = validate_subscription(value)
        identity = sha256(value['endpoint'].encode()).hexdigest()
        with self.db() as db:
            db.execute('INSERT INTO subscriptions VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET owner=excluded.owner,data=excluded.data', (identity,self.owner,json.dumps(value),time.time()))
        return identity

    def remove(self, endpoint):
        identity = sha256(endpoint.encode()).hexdigest()
        with self.db() as db:
            db.execute('DELETE FROM subscriptions WHERE id=? AND owner=?', (identity,self.owner))
            db.execute('DELETE FROM delivered WHERE subscription=?', (identity,))

    def subscriptions(self):
        with self.db() as db:
            return [(i,json.loads(d),since) for i,d,since in db.execute('SELECT id,data,since FROM subscriptions WHERE owner=?',(self.owner,))]

    def mark_read(self, keys):
        with self.db() as db:
            db.executemany('INSERT OR REPLACE INTO reads VALUES (?,?,?)', [(k['remoteJid'], k['id'], time.time()) for k in keys])
            db.execute('DELETE FROM reads WHERE ts<?', (time.time()-60*86400,))

    def receipts(self):
        with self.db() as db:
            return {jid+'|'+mid: True for jid,mid in db.execute('SELECT jid,mid FROM reads ORDER BY ts DESC LIMIT 10000')}

    def deliver(self, records, checked_at, aliases=None, send=webpush):
        self.last_error = None
        aliases = aliases or {}
        def canonical(jid):
            return aliases.get(jid, jid.split('@')[0] if jid.endswith('@s.whatsapp.net') else jid)
        reads = {(canonical(key.rsplit('|',1)[0]),key.rsplit('|',1)[1]) for key in self.receipts()}
        delivered_count = 0
        for identity, subscription, since in self.subscriptions():
            with self.db() as db:
                sent = {row[0] for row in db.execute('SELECT message FROM delivered WHERE subscription=?',(identity,))}
            pending = {}
            for rec in records:
                key = rec.get('key') or {};jid=key.get('remoteJid') or '';mid=key.get('id') or ''
                ts = float(rec.get('messageTimestamp') or 0)
                token = canonical(jid)+'|'+mid
                if not mid or not jid or key.get('fromMe') or jid=='status@broadcast' or ts < since or ts > checked_at or token in sent or (canonical(jid),mid) in reads or rec.get('status') in ('READ','PLAYED',4,5):
                    continue
                pending[token] = jid
            if pending:
                # One visible summary per device/cycle; no private message body in push.
                jid = next(reversed(pending.values()))
                payload = json.dumps({'title':'WhatsApp','body':'Você recebeu novas mensagens.','tag':'wa-messages','url':'/?chat='+quote(jid,safe='')})
                try:
                    response = send(subscription_info=subscription, data=payload,
                                    vapid_private_key=Vapid.from_pem(self.key().encode()), vapid_claims={'sub':'https://wa-web.jdbhwl.easypanel.host'}, ttl=300, timeout=10)
                    if response is not None and response.status_code >= 300:
                        self.last_error = 'Falha na entrega de notificações; nova tentativa automática.'
                        continue
                except WebPushException as exc:
                    if exc.response is not None and exc.response.status_code in (404,410):
                        self.remove(subscription['endpoint'])
                    else:
                        self.last_error = 'Falha na entrega de notificações; nova tentativa automática.'
                    continue
                except Exception:
                    # No secrets/endpoints in logs; retain checkpoint for next poll.
                    self.last_error = 'Falha na entrega de notificações; nova tentativa automática.'
                    continue
                with self.db() as db:
                    db.executemany('INSERT OR IGNORE INTO delivered VALUES (?,?,?)',[(identity,token,checked_at) for token in pending])
                delivered_count += 1
            with self.db() as db:
                db.execute('UPDATE subscriptions SET since=? WHERE id=? AND owner=?',(max(since,checked_at-120),identity,self.owner))
                db.execute('DELETE FROM delivered WHERE ts<?',(checked_at-7*86400,))
        return delivered_count
