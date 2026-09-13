# -*- coding: utf-8 -*-
"""wa-web — WhatsApp Web próprio em cima da Evolution API v2 (Baileys).

Substitui o WhatsApp Web quando só a API está acessível: lista de chats com não-lidos,
conversa paginada (50/pág, limite fixo da Evolution), mídia (imagem/áudio/vídeo/doc),
envio de texto, marcar como lido e transcrição de áudio via o serviço `transcriber`.

Env:
  EVOLUTION_URL, EVOLUTION_APIKEY, EVOLUTION_INSTANCE  — a Evolution que segura o número
  WA_PASSWORD        — senha única de acesso (cookie assinado com WA_SECRET)
  WA_SECRET          — segredo do cookie (gerado se ausente; login cai a cada restart)
  TRANSCRIBER_URL, TRANSCRIBER_TOKEN — opcional; sem eles o botão "transcrever" some
"""
import asyncio
import base64
import hmac
import os
import re
import secrets
import time
import tempfile
from copy import deepcopy
from collections import OrderedDict
from hashlib import sha256
from pathlib import Path

import httpx
from storage import PersistentCache
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

EVO = os.environ["EVOLUTION_URL"].rstrip("/")
KEY = os.environ["EVOLUTION_APIKEY"]
INST = os.environ.get("EVOLUTION_INSTANCE", "solaris")
PASSWORD = os.environ["WA_PASSWORD"]
SECRET = os.environ.get("WA_SECRET") or secrets.token_urlsafe(32)
TR_URL = os.environ.get("TRANSCRIBER_URL", "").rstrip("/")
TR_TOKEN = os.environ.get("TRANSCRIBER_TOKEN", "")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.environ.get("GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3")
GROQ_LANGUAGE = os.environ.get("GROQ_TRANSCRIPTION_LANGUAGE", "").strip()
COOKIE = "wa_session"
_disk = PersistentCache(os.environ.get("WA_CACHE_DIR"), EVO + "|" + INST)
_media_policy = OrderedDict()


def _persistent_identity(jid, mid):
    return jid + "|" + mid


def _transcript_identity(jid, mid):
    provider = "groq|" + GROQ_MODEL + "|" + GROQ_LANGUAGE if GROQ_KEY else "local|" + TR_URL
    return _persistent_identity(jid, mid) + "|" + provider + "|v1"


def _can_persist(jid, mid):
    return _media_policy.get((jid, mid)) is True
HTML = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")

app = FastAPI(title="wa-web")
evo = httpx.AsyncClient(base_url=EVO, headers={"apikey": KEY}, timeout=120)


@app.middleware("http")
async def private_responses(req: Request, call_next):
    resp = await call_next(req)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if req.url.path.startswith("/api/") and req.url.path != "/api/media":
        resp.headers["Cache-Control"] = "no-store"
    return resp

# ---------------------------------------------------------------- auth
_token = hmac.new(SECRET.encode(), b"wa-web-ok", sha256).hexdigest()
_fails: dict[str, list[float]] = {}  # ponytail: lockout em memória; por-IP, some no restart


def _authed(req: Request) -> bool:
    return hmac.compare_digest(req.cookies.get(COOKIE, ""), _token)


def _need(req: Request):
    if not _authed(req):
        raise HTTPException(401, "login")


@app.post("/api/login")
async def login(req: Request, resp: Response):
    ip = req.client.host if req.client else "?"
    now = time.time()
    _fails[ip] = [t for t in _fails.get(ip, []) if now - t < 600]
    if len(_fails[ip]) >= 5:
        raise HTTPException(429, "muitas tentativas — espere 10 min")
    body = await req.json()
    if not hmac.compare_digest(str(body.get("senha", "")), PASSWORD):
        _fails[ip].append(now)
        raise HTTPException(401, "senha errada")
    resp.set_cookie(COOKIE, _token, httponly=True, secure=True, samesite="lax", max_age=60 * 86400)
    return {"ok": True}


@app.post("/api/logout")
def logout(resp: Response):
    resp.delete_cookie(COOKIE)
    return {"ok": True}


# ---------------------------------------------------------------- helpers
async def _post(path: str, body: dict | None = None) -> dict | list:
    try:
        r = await evo.post(path, json=body or {})
    except httpx.RequestError:
        raise HTTPException(504, "Não foi possível confirmar a operação. Atualize a conversa antes de tentar novamente.")
    if r.status_code >= 400:
        raise HTTPException(502, f"evolution {r.status_code}: {r.text[:200]}")
    return r.json()


def _contact(card: dict) -> dict:
    """Extract display fields only; never expose or execute arbitrary vCard URLs."""
    name = str(card.get("displayName") or "").strip()
    phones = []
    lines = re.sub(r"\r?\n[ \t]", "", str(card.get("vcard") or "")).splitlines()
    for line in lines:
        header, sep, value = line.partition(":")
        if not sep:
            continue
        field = header.split(";", 1)[0].split(".")[-1].upper()
        if field == "FN" and not name:
            name = re.sub(r"\\([nN,;\\])", lambda m: " " if m[1].lower() == "n" else m[1], value).strip()
        if field != "TEL":
            continue
        waid = re.search(r'(?:^|;)waid="?([0-9]{7,15})"?(?:;|$)', header, re.I)
        raw = re.sub(r"^tel:", "", value.strip(), flags=re.I)
        number = waid[1] if waid else re.sub(r"[+().\s-]", "", raw)
        if re.fullmatch(r"[0-9]{7,15}", number) and number not in phones:
            phones.append(number)
    return {"name": name or "Contato compartilhado", "phones": phones}


def _body(msg: dict) -> tuple[str, str, dict]:
    """(tipo, texto, extra) a partir de message{}."""
    m = msg.get("message") or {}
    for _ in range(4):
        wrapped = next((m.get(k, {}).get("message") for k in
                        ("ephemeralMessage", "viewOnceMessage", "viewOnceMessageV2", "documentWithCaptionMessage")
                        if isinstance(m.get(k), dict) and m[k].get("message")), None)
        if not wrapped:
            break
        m = wrapped
    if m.get("conversation"):
        return "text", m["conversation"], {}
    if m.get("extendedTextMessage"):
        return "text", m["extendedTextMessage"].get("text", ""), {}
    if m.get("imageMessage"):
        return "image", m["imageMessage"].get("caption", ""), {"mime": m["imageMessage"].get("mimetype")}
    if m.get("videoMessage"):
        return "video", m["videoMessage"].get("caption", ""), {"mime": m["videoMessage"].get("mimetype")}
    if m.get("audioMessage"):
        a = m["audioMessage"]
        return "audio", "", {"seconds": a.get("seconds"), "mime": a.get("mimetype")}
    if m.get("documentMessage"):
        d = m["documentMessage"]
        return "document", d.get("caption", ""), {"fileName": d.get("fileName"), "mime": d.get("mimetype"), "size": d.get("fileLength")}
    if m.get("stickerMessage"):
        return "sticker", "", {}
    if m.get("reactionMessage"):
        return "reaction", m["reactionMessage"].get("text", ""), {"to": m["reactionMessage"].get("key", {}).get("id")}
    if m.get("locationMessage"):
        loc = m["locationMessage"]
        return "text", f"📍 {loc.get('degreesLatitude')},{loc.get('degreesLongitude')}", {}
    if m.get("contactMessage"):
        contact = _contact(m["contactMessage"])
        return "contact", contact["name"], {"contacts": [contact]}
    if m.get("contactsArrayMessage"):
        contacts = [_contact(c) for c in m["contactsArrayMessage"].get("contacts", []) if isinstance(c, dict)]
        return "contact", ", ".join(c["name"] for c in contacts), {"contacts": contacts}
    keys = [k for k in m if k != "messageContextInfo"]
    return "other", "", {"kind": keys[0] if keys else "?"}


def _norm(rec: dict) -> dict:
    k = rec.get("key") or {}
    typ, txt, extra = _body(rec)
    content = rec.get("message") or {}
    cacheable = True
    for _ in range(4):
        if any(name in content for name in ("ephemeralMessage", "viewOnceMessage", "viewOnceMessageV2", "viewOnceMessageV2Extension")):
            cacheable = False
        wrapped = next((v.get("message") for v in content.values()
                        if isinstance(v, dict) and isinstance(v.get("message"), dict)), None)
        if not wrapped:
            break
        content = wrapped
    context = next((v["contextInfo"] for v in content.values()
                    if isinstance(v, dict) and isinstance(v.get("contextInfo"), dict)), {})
    quoted = context.get("quotedMessage") or {}
    cacheable = cacheable and not context.get("expiration") and typ != "other"
    _media_policy[(k.get("remoteJid") or "", k.get("id") or "")] = bool(cacheable)
    while len(_media_policy) > 10000:
        _media_policy.popitem(last=False)
    qtype, qtext, _ = _body({"message": quoted}) if quoted else ("", "", {})
    return {
        "id": k.get("id"),
        "cacheable": bool(cacheable),
        "fromMe": bool(k.get("fromMe")),
        "ts": rec.get("messageTimestamp") or 0,
        "who": rec.get("pushName") or "",
        "participant": (k.get("participant") or "").split("@")[0],
        "type": typ,
        "text": txt,
        "jid": k.get("remoteJid") or "",
        "participantJid": k.get("participant") or "",
        "status": rec.get("status"),
        "quote": {"id": context.get("stanzaId"), "text": qtext, "type": qtype} if quoted else None,
        "transcript": _trans.get(_transcript_identity(k.get("remoteJid") or "", k.get("id") or "")),
        "transcription": _trans_meta.get(_transcript_identity(k.get("remoteJid") or "", k.get("id") or "")),
        **extra,
    }


def _number(chat_jid: str, alt: str) -> str:
    if chat_jid.endswith("@g.us"):
        return chat_jid
    if alt and alt.endswith("@s.whatsapp.net"):
        return alt.split("@")[0]
    if chat_jid.endswith("@s.whatsapp.net"):
        return chat_jid.split("@")[0]
    return chat_jid  # @lid sem alt: a Evolution aceita o jid cru


# ---------------------------------------------------------------- api
@app.get("/api/state")
async def state(req: Request):
    _need(req)
    try:
        r = await evo.get(f"/instance/connectionState/{INST}")
        r.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(502, "Não foi possível verificar a conexão do WhatsApp.")
    return r.json()


@app.get("/api/session")
def session(req: Request):
    _need(req)
    return {"ok": True, "transcriber": bool(GROQ_KEY or TR_URL),
            "transcriptionModel": GROQ_MODEL if GROQ_KEY else "local", "version": "2026.09.13.6",
            "cacheScope": hmac.new(SECRET.encode(), ("cache:"+EVO+":"+INST).encode(), sha256).hexdigest()}


@app.get("/api/profile")
async def profile(req: Request, number: str):
    _need(req)
    if not re.fullmatch(r"[0-9]{5,20}(?:@(?:s\.whatsapp\.net|lid))?", number):
        raise HTTPException(400, "Número de contato inválido.")
    try:
        data = await asyncio.wait_for(_post(f"/chat/fetchProfile/{INST}", {"number": number}), 25)
    except (HTTPException, asyncio.TimeoutError):
        raise HTTPException(502, "Não foi possível carregar o perfil. Tente novamente.")
    about = data.get("status") or {}
    result = {"name": data.get("name") or "", "picture": data.get("picture") or "",
              "about": about.get("status", "") if isinstance(about, dict) else str(about),
              "aboutUpdated": str(about.get("setAt") or "") if isinstance(about, dict) else "",
              "business": bool(data.get("isBusiness")), "fields": {}, "partial": False}
    if not str(result['picture']).startswith('https://'):
        result['picture'] = ''
    if result['business']:
        try:
            business = await asyncio.wait_for(_post(f"/chat/fetchBusinessProfile/{INST}", {"number": number}), 15)
            result['fields'] = {k: business[k] for k in ('description','email','address','website','category','business_hours') if business.get(k)}
        except (HTTPException, asyncio.TimeoutError):
            result['partial'] = True
    return result


@app.get("/api/chats")
async def chats(req: Request):
    _need(req)
    data = await _post(f"/chat/findChats/{INST}")
    recs = data.get("records") if isinstance(data, dict) else data
    # A Evolution separa o mesmo contato em 2 chats: o que ELE manda cai no `@lid`,
    # o que EU mando cai no `<numero>@s.whatsapp.net`. Funde por número.
    merged: dict[str, dict] = {}
    for c in recs or []:
        lm = c.get("lastMessage") or {}
        k = lm.get("key") or {}
        typ, txt, extra = _body(lm) if lm else ("text", "", {})
        jid = c.get("remoteJid") or ""
        number = _number(jid, k.get("remoteJidAlt") or "")
        item = {
            "jid": jid, "jids": [jid],
            "name": c.get("pushName") or ("" if (jid.endswith("@g.us") or k.get("fromMe")) else lm.get("pushName") or ""),
            "number": number,
            "group": jid.endswith("@g.us"),
            "unread": c.get("unreadCount") or 0,
            "unreadSources": [{"jid": jid, "count": max(0, int(c.get("unreadCount") or 0)),
                               "lastId": k.get("id") or "", "ts": lm.get("messageTimestamp") or 0}],
            "ts": lm.get("messageTimestamp") or 0,
            "fromMe": bool(k.get("fromMe")),
            "who": lm.get("pushName") or "",
            "ptype": typ,
            "cacheable": _norm(lm)["cacheable"] if lm else False,
            "preview": txt or extra.get("fileName") or "",
            "seconds": extra.get("seconds"),
            "pic": c.get("profilePicUrl") or "",
        }
        prev = merged.get(number)
        if not prev:
            merged[number] = item
            continue
        newer, older = (item, prev) if item["ts"] > prev["ts"] else (prev, item)
        newer["jids"] = sorted(set(prev["jids"] + item["jids"]))
        newer["unread"] = prev["unread"] + item["unread"]
        newer["unreadSources"] = prev["unreadSources"] + item["unreadSources"]
        newer["name"] = newer["name"] or older["name"]
        newer["pic"] = newer["pic"] or older["pic"]
        if newer["jid"].endswith("@s.whatsapp.net") and older["jid"].endswith("@lid"):
            newer["jid"] = older["jid"]  # o @lid é onde as respostas dele chegam
        merged[number] = newer
    out = sorted(merged.values(), key=lambda c: c["ts"], reverse=True)
    return out


_cursors: OrderedDict[str, tuple[float, dict]] = OrderedDict()


async def _fill_stream(stream: dict):
    if stream["queue"] or stream["done"]:
        return
    data = await _post(f"/chat/findMessages/{INST}",
                       {"where": {"key": {"remoteJid": stream["jid"]}}, "limit": 50, "page": stream["page"]})
    result = data.get("messages") or {}
    stream["queue"] = sorted(result.get("records") or [], key=lambda r: int(r.get("messageTimestamp") or 0), reverse=True)
    stream["done"] = stream["page"] >= int(result.get("pages") or 1) or not stream["queue"]
    stream["page"] += 1


@app.get("/api/messages")
async def messages(req: Request, jid: str, extra: str = "", cursor: str = ""):
    """Merge the newest frontiers of all JIDs; older pages never outrun a sibling.

    Opaque short-lived cursors preserve buffered records and can be retried safely.
    Each request advances a copy, leaving the previous cursor unchanged on failure.
    """
    _need(req)
    jids = sorted(set([jid] + [j for j in extra.split(",") if j]))
    if not jid or len(jids) > 8:
        raise HTTPException(400, "Conversa inválida.")
    now = time.monotonic()
    if cursor:
        entry = _cursors.get(cursor)
        if not entry or now - entry[0] > 1800 or entry[1]["jids"] != jids:
            raise HTTPException(410, "O histórico expirou. Reabra a conversa para continuar.")
        snapshot = deepcopy(entry[1])
    else:
        snapshot = {"jids": jids, "streams": [{"jid": j, "page": 1, "queue": [], "done": False} for j in jids], "seen": set()}
    streams = snapshot["streams"]
    await asyncio.gather(*(_fill_stream(s) for s in streams))
    output, alt = [], ""
    # Bound pathological duplicate pages while permitting normal merged histories.
    for _ in range(500):
        ready = [s for s in streams if s["queue"]]
        if not ready or len(output) >= 50:
            break
        stream = max(ready, key=lambda s: int(s["queue"][0].get("messageTimestamp") or 0))
        rec = stream["queue"].pop(0)
        rec.setdefault("key", {}).setdefault("remoteJid", stream["jid"])
        key = rec["key"]
        candidate = key.get("remoteJidAlt") or ""
        if candidate.endswith("@s.whatsapp.net"):
            alt = candidate
        msg = _norm(rec)
        if msg["id"] and msg["id"] not in snapshot["seen"]:
            snapshot["seen"].add(msg["id"])
            output.append(msg)
        if len(output) < 50:
            await _fill_stream(stream)
    has_more = any(s["queue"] or not s["done"] for s in streams)
    next_cursor = ""
    if has_more:
        next_cursor = secrets.token_urlsafe(24)
        _cursors[next_cursor] = (now, snapshot)
        while len(_cursors) > 128:
            _cursors.popitem(last=False)
    output.sort(key=lambda m: (int(m["ts"]), m["id"]))
    for msg in output:
        if msg["cacheable"] and msg["type"] == "audio" and msg["transcript"] is None:
            saved = await asyncio.to_thread(_disk.get, "transcript", _transcript_identity(msg["jid"], msg["id"]))
            if saved is not None:
                msg["transcript"] = saved["texto"]
                msg["transcription"] = {k: v for k, v in saved.items() if k != "texto"}
    return {"messages": output, "cursor": next_cursor, "hasMore": has_more, "number": _number(jid, alt)}


_media: OrderedDict[str, tuple[str, bytes]] = OrderedDict()


async def _fetch_media(jid: str, mid: str) -> tuple[str, bytes]:
    identity = _persistent_identity(jid, mid)
    if _can_persist(jid, mid) and identity in _media:
        _media.move_to_end(identity)
        return _media[identity]
    if _can_persist(jid, mid):
        saved = await asyncio.to_thread(_disk.get, "media", identity)
        if saved is not None:
            return saved
    d = await _post(f"/chat/getBase64FromMediaMessage/{INST}",
                    {"message": {"key": {"id": mid, "remoteJid": jid}}, "convertToMp4": False})
    mime = d.get("mimetype") or "application/octet-stream"
    raw = base64.b64decode(d["base64"])
    if _can_persist(jid, mid):
        await asyncio.to_thread(_disk.put, "media", identity, (mime, raw))
        _media[identity] = (mime, raw)
    while sum(len(value[1]) for value in _media.values()) > 64 * 1024**2 or len(_media) > 200:
        _media.popitem(last=False)
    return mime, raw


@app.get("/api/media")
async def media(req: Request, jid: str, id: str):
    _need(req)
    mime, raw = await _fetch_media(jid, id)
    headers = {"Cache-Control": "private, max-age=86400", "Accept-Ranges": "bytes"}
    requested = req.headers.get("range")
    if requested:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
        if not match or not any(match.groups()) or not raw:
            return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{len(raw)}"})
        first, last = match.groups()
        start = int(first) if first else max(0, len(raw) - int(last))
        end = min(int(last), len(raw) - 1) if first and last else len(raw) - 1
        if start > end or start >= len(raw):
            return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{len(raw)}"})
        return Response(raw[start:end + 1], status_code=206, media_type=mime.split(";")[0],
                        headers={**headers, "Content-Range": f"bytes {start}-{end}/{len(raw)}"})
    return Response(raw, media_type=mime.split(";")[0], headers=headers)


@app.post("/api/send")
async def send(req: Request):
    _need(req)
    body = await req.json()
    text = (body.get("text") or "").strip()
    if not text or len(text) > 20000:
        raise HTTPException(400, "texto vazio")
    number = str(body.get("number") or "")
    if not number:
        raise HTTPException(400, "Destinatário ausente.")
    request_id = str(body.get("requestId") or "")[:100]
    payload = {"number": number, "text": text}
    if request_id:
        entry = _sends.get(request_id)
        if entry:
            if entry[0] != payload:
                raise HTTPException(409, "Este envio já foi usado para outra mensagem.")
            task = entry[1]
        else:
            if len(_sends) >= 512:
                finished = next((k for k, v in _sends.items() if v[1].done()), None)
                if finished is None:
                    raise HTTPException(429, "Há muitos envios em andamento. Aguarde.")
                _sends.pop(finished)
            task = asyncio.create_task(_post(f"/message/sendText/{INST}", payload))
            _sends[request_id] = (payload, task)
        d = await asyncio.shield(task)
    else:
        d = await _post(f"/message/sendText/{INST}", payload)
    return {"id": (d.get("key") or {}).get("id"), "status": d.get("status")}


_sends: OrderedDict[str, tuple[dict, asyncio.Task]] = OrderedDict()

# Recorder formats vary (WebM/Opus in Chrome, MP4/AAC in Safari).
# Convert locally to a WhatsApp voice note. No remote URL or third-party encoder.
MAX_AUDIO = 12 * 1024 * 1024
_audio_slots = asyncio.Semaphore(2)


async def _voice_ogg(raw: bytes) -> bytes:
    async with _audio_slots:
        with tempfile.TemporaryDirectory(prefix="wa-voice-") as folder:
            source, target = Path(folder) / "recording", Path(folder) / "voice.ogg"
            source.write_bytes(raw)
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                    "-protocol_whitelist", "file,pipe", "-i", str(source), "-vn",
                    "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-c:a", "libopus",
                    "-b:a", "32k", "-application", "voip", "-t", "601", str(target),
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            except FileNotFoundError:
                raise HTTPException(503, "O gravador está temporariamente indisponível no servidor.")
            try:
                await asyncio.wait_for(proc.wait(), 45)
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
            if proc.returncode or not target.exists() or target.stat().st_size < 100:
                raise HTTPException(400, "Não foi possível ler este áudio. Grave novamente ou escolha outro arquivo.")
            encoded = target.read_bytes()
            # Ogg Opus last-page granule is the decoded sample count (48 kHz).
            last_page = encoded.rfind(b"OggS")
            samples = int.from_bytes(encoded[last_page + 6:last_page + 14], "little")
            # Allow recorder scheduling/encoder padding at the ten-minute boundary.
            # The 601 s conversion cap remains above this threshold, so longer
            # inputs are rejected rather than silently truncated and sent.
            if samples > 600 * 48000 + 24000:
                raise HTTPException(400, "O áudio deve ter no máximo 10 minutos.")
            return encoded


async def _send_voice(raw: bytes, number: str):
    try:
        encoded = await _voice_ogg(raw)
    except asyncio.TimeoutError:
        raise HTTPException(503, "O áudio demorou para processar. Tente um áudio mais curto.")
    data = await _post(f"/message/sendWhatsAppAudio/{INST}",
                       {"number": number, "audio": base64.b64encode(encoded).decode(), "encoding": False})
    mid = (data.get("key") or {}).get("id")
    return {"id": mid, "status": data.get("status")}


@app.post("/api/send-audio")
async def send_audio(req: Request, number: str, requestId: str):
    _need(req)
    if not number or len(number) > 100 or not requestId or len(requestId) > 100:
        raise HTTPException(400, "Destinatário ou identificação do envio inválidos.")
    if req.headers.get("content-type", "").split(";")[0] not in {
        "audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav",
        "audio/x-wav", "audio/aac", "video/mp4", "application/octet-stream"}:
        raise HTTPException(415, "Escolha um arquivo de áudio compatível.")
    raw = bytearray()
    async for chunk in req.stream():
        if len(raw) + len(chunk) > MAX_AUDIO:
            raise HTTPException(413, "O áudio deve ter até 12 MB.")
        raw.extend(chunk)
    if not raw:
        raise HTTPException(400, "O áudio está vazio.")
    fingerprint = {"kind": "audio", "number": number, "sha256": sha256(raw).hexdigest()}
    entry = _sends.get(requestId)
    if entry:
        if entry[0] != fingerprint:
            raise HTTPException(409, "Este envio já foi usado para outra mensagem.")
        task = entry[1]
    else:
        if len(_sends) >= 512:
            finished = next((k for k, v in _sends.items() if v[1].done()), None)
            if finished is None:
                raise HTTPException(429, "Há muitos envios em andamento. Aguarde.")
            _sends.pop(finished)
        task = asyncio.create_task(_send_voice(bytes(raw), number))
        _sends[requestId] = (fingerprint, task)
    return await asyncio.shield(task)


@app.post("/api/send-image")
async def send_image(req: Request, number: str, requestId: str):
    _need(req)
    if not number or len(number) > 100 or not requestId or len(requestId) > 100:
        raise HTTPException(400, "Destinatário ou identificação do envio inválidos.")
    raw = bytearray()
    async for chunk in req.stream():
        if len(raw) + len(chunk) > 10 * 1024 * 1024:
            raise HTTPException(413, "A imagem deve ter até 10 MB.")
        raw.extend(chunk)
    mime = "image/png" if raw.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg" if raw.startswith(b"\xff\xd8\xff") else ""
    if not mime:
        raise HTTPException(415, "Cole uma imagem PNG ou JPEG.")
    fingerprint = {"kind": "image", "number": number, "sha256": sha256(raw).hexdigest()}
    entry = _sends.get(requestId)
    if entry:
        if entry[0] != fingerprint:
            raise HTTPException(409, "Este envio já foi usado para outra mensagem.")
        task = entry[1]
    else:
        if len(_sends) >= 512:
            finished = next((k for k, v in _sends.items() if v[1].done()), None)
            if finished is None:
                raise HTTPException(429, "Há muitos envios em andamento. Aguarde.")
            _sends.pop(finished)
        payload = {"number": number, "mediatype": "image", "mimetype": mime,
                   "caption": "", "fileName": "print.png" if mime == "image/png" else "print.jpg",
                   "media": base64.b64encode(raw).decode()}
        task = asyncio.create_task(_post(f"/message/sendMedia/{INST}", payload))
        _sends[requestId] = (fingerprint, task)
    data = await asyncio.shield(task)
    return {"id": (data.get("key") or {}).get("id"), "status": data.get("status")}


@app.post("/api/read")
async def read(req: Request):
    _need(req)
    body = await req.json()
    items = [{"remoteJid": str(k.get("jid") or body.get("jid") or ""), "fromMe": False,
              "id": str(k.get("id") or ""), **({"participant": k["participant"]} if k.get("participant") else {})}
             for k in (body.get("keys") or [{"id": i} for i in body.get("ids") or []])[:100]]
    items = [k for k in items if k["id"] and k["remoteJid"]]
    if not items:
        return {"ok": True}
    await _post(f"/chat/markMessageAsRead/{INST}", {"readMessages": items})
    return {"ok": True}


_trans: OrderedDict[str, str] = OrderedDict()
_trans_meta: dict[str, dict] = {}
_trans_tasks: dict[tuple[str, str], asyncio.Task] = {}
_trans_slots = asyncio.Semaphore(2)


async def _groq_transcribe(mime: str, raw: bytes) -> dict:
    if len(raw) > 25_000_000:
        raise HTTPException(413, "Este áudio ultrapassa 25 MB. Use um trecho menor para transcrever.")
    extension = {"audio/ogg": "ogg", "audio/opus": "ogg", "audio/mpeg": "mp3",
                 "audio/mp4": "m4a", "audio/x-m4a": "m4a", "video/mp4": "mp4",
                 "audio/webm": "webm", "audio/wav": "wav", "audio/x-wav": "wav",
                 "audio/flac": "flac"}.get(mime.split(";")[0], "ogg")
    data = {"model": GROQ_MODEL, "response_format": "verbose_json", "temperature": "0"}
    if GROQ_LANGUAGE:
        data["language"] = GROQ_LANGUAGE
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15)) as client:
            response = await client.post("https://api.groq.com/openai/v1/audio/transcriptions",
                                         headers={"Authorization": f"Bearer {GROQ_KEY}"}, data=data,
                                         files={"file": (f"audio.{extension}", raw, mime.split(";")[0])})
    except httpx.TimeoutException:
        raise HTTPException(504, "A transcrição demorou mais que o esperado. Tente novamente em instantes.")
    except httpx.RequestError:
        raise HTTPException(502, "Não foi possível conectar ao serviço de transcrição. Tente novamente.")
    if response.status_code in (401, 403):
        raise HTTPException(503, "A chave da transcrição não foi aceita. Confira a configuração do serviço.")
    if response.status_code == 429:
        raise HTTPException(429, "O limite da transcrição foi atingido. Aguarde um pouco e tente novamente.",
                            headers={"Retry-After": "60"})
    if response.status_code >= 400:
        raise HTTPException(502, "O serviço não conseguiu transcrever este áudio. Tente novamente ou use outro arquivo.")
    try:
        result = response.json()
        text = str(result.get("text") or "").strip()
        segments = [{"start": max(0, float(s.get("start") or 0)),
                     "end": max(0, float(s.get("end") or 0)), "text": str(s.get("text") or "").strip()}
                    for s in (result.get("segments") or []) if str(s.get("text") or "").strip()]
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(502, "A transcrição retornou uma resposta inválida. Tente novamente.")
    return {"texto": text, "segments": segments, "language": result.get("language"),
            "model": GROQ_MODEL, "provider": "Groq"}


async def _legacy_transcribe(mid: str, mime: str, raw: bytes):
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(f"{TR_URL}/api/upload", headers={"X-Token": TR_TOKEN},
                         files={"file": (f"{mid}.ogg", raw, mime.split(";")[0])})
        if r.status_code >= 400:
            raise HTTPException(502, f"transcriber {r.status_code}: {r.text[:150]}")
        job = r.json()["id"]
        for _ in range(90):
            t = await c.get(f"{TR_URL}/api/jobs/{job}/texto", headers={"X-Token": TR_TOKEN})
            if t.status_code == 200:
                txt = (t.json().get("texto") or "").strip()
                return {"texto": txt, "provider": "local", "segments": []}
            await asyncio.sleep(2)
    raise HTTPException(504, "transcrição demorou demais")


async def _transcribe_message(jid: str, mid: str):
    async with _trans_slots:
        mime, raw = await _fetch_media(jid, mid)
        result = await _groq_transcribe(mime, raw) if GROQ_KEY else await _legacy_transcribe(mid, mime, raw)
        if _can_persist(jid, mid):
            await asyncio.to_thread(_disk.put, "transcript", _transcript_identity(jid, mid), result)
        identity = _transcript_identity(jid, mid)
        _trans[identity] = result["texto"]
        _trans_meta[identity] = {k: v for k, v in result.items() if k != "texto"}
        while len(_trans) > 1000:
            removed, _ = _trans.popitem(last=False)
            _trans_meta.pop(removed, None)
        return result


@app.post("/api/transcribe")
async def transcribe(req: Request):
    _need(req)
    if not GROQ_KEY and not TR_URL:
        raise HTTPException(501, "Transcrição não configurada.")
    body = await req.json()
    jid, mid = str(body.get("jid") or ""), str(body.get("id") or "")
    if not jid or not mid or len(jid) > 150 or len(mid) > 150:
        raise HTTPException(400, "Identificação do áudio inválida.")
    identity = _transcript_identity(jid, mid)
    if identity in _trans:
        return {"texto": _trans[identity], **_trans_meta.get(identity, {}), "cached": True}
    key = (jid, mid)
    if _can_persist(jid, mid):
        saved = await asyncio.to_thread(_disk.get, "transcript", _transcript_identity(jid, mid))
        if saved is not None:
            return {**saved, "cached": True}
    task = _trans_tasks.get(key)
    if task is None:
        if len(_trans_tasks) >= 32:
            raise HTTPException(429, "Há muitas transcrições em andamento. Aguarde um pouco.")
        task = asyncio.create_task(_transcribe_message(jid, mid))
        _trans_tasks[key] = task
        def finished(completed):
            if _trans_tasks.get(key) is completed:
                _trans_tasks.pop(key, None)
            if not completed.cancelled():
                completed.exception()  # consume errors even if the HTTP client disconnected
        task.add_done_callback(finished)
    return await asyncio.shield(task)


@app.get("/healthz")
def healthz():
    return {"ok": True, "instance": INST, "transcriber": bool(GROQ_KEY or TR_URL), "version": "2026.09.13.6"}


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(HTML, headers={"Cache-Control": "no-cache"})


@app.get("/app.js")
def javascript():
    return Response((Path(__file__).parent / "app.js").read_text(encoding="utf-8"), media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/style.css")
def stylesheet():
    return Response((Path(__file__).parent / "style.css").read_text(encoding="utf-8"), media_type="text/css", headers={"Cache-Control": "no-cache"})


@app.get("/{asset}")
def app_asset(asset: str):
    public_assets = {"cache.js": "application/javascript", "voice.js": "application/javascript", "pwa.js": "application/javascript",
                     "sw.js": "application/javascript", "manifest.webmanifest": "application/manifest+json",
                     "icon-192.png": "image/png", "icon-512.png": "image/png", "apple-touch-icon.png": "image/png",
                     "offline.html": "text/html"}
    if asset not in public_assets:
        raise HTTPException(404)
    return Response((Path(__file__).parent / asset).read_bytes(), media_type=public_assets[asset],
                    headers={"Cache-Control": "no-cache"})
