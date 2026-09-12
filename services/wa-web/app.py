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
import secrets
import time
from collections import OrderedDict
from hashlib import sha256
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

EVO = os.environ["EVOLUTION_URL"].rstrip("/")
KEY = os.environ["EVOLUTION_APIKEY"]
INST = os.environ.get("EVOLUTION_INSTANCE", "solaris")
PASSWORD = os.environ["WA_PASSWORD"]
SECRET = os.environ.get("WA_SECRET") or secrets.token_urlsafe(32)
TR_URL = os.environ.get("TRANSCRIBER_URL", "").rstrip("/")
TR_TOKEN = os.environ.get("TRANSCRIBER_TOKEN", "")
COOKIE = "wa_session"
HTML = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")

app = FastAPI(title="wa-web")
evo = httpx.AsyncClient(base_url=EVO, headers={"apikey": KEY}, timeout=120)

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
    r = await evo.post(path, json=body or {})
    if r.status_code >= 400:
        raise HTTPException(502, f"evolution {r.status_code}: {r.text[:200]}")
    return r.json()


def _body(msg: dict) -> tuple[str, str, dict]:
    """(tipo, texto, extra) a partir de message{}."""
    m = msg.get("message") or {}
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
        return "document", d.get("caption", ""), {"fileName": d.get("fileName"), "mime": d.get("mimetype")}
    if m.get("stickerMessage"):
        return "sticker", "", {}
    if m.get("reactionMessage"):
        return "reaction", m["reactionMessage"].get("text", ""), {"to": m["reactionMessage"].get("key", {}).get("id")}
    if m.get("locationMessage"):
        loc = m["locationMessage"]
        return "text", f"📍 {loc.get('degreesLatitude')},{loc.get('degreesLongitude')}", {}
    if m.get("contactMessage"):
        return "text", "👤 " + m["contactMessage"].get("displayName", "contato"), {}
    keys = [k for k in m if k != "messageContextInfo"]
    return "other", "", {"kind": keys[0] if keys else "?"}


def _norm(rec: dict) -> dict:
    k = rec.get("key") or {}
    typ, txt, extra = _body(rec)
    return {
        "id": k.get("id"),
        "fromMe": bool(k.get("fromMe")),
        "ts": rec.get("messageTimestamp") or 0,
        "who": rec.get("pushName") or "",
        "participant": (k.get("participant") or "").split("@")[0],
        "type": typ,
        "text": txt,
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
    r = await evo.get(f"/instance/connectionState/{INST}")
    return r.json()


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
            "ts": lm.get("messageTimestamp") or 0,
            "fromMe": bool(k.get("fromMe")),
            "who": lm.get("pushName") or "",
            "ptype": typ,
            "preview": txt or extra.get("fileName") or "",
            "pic": c.get("profilePicUrl") or "",
        }
        prev = merged.get(number)
        if not prev:
            merged[number] = item
            continue
        newer, older = (item, prev) if item["ts"] > prev["ts"] else (prev, item)
        newer["jids"] = sorted(set(prev["jids"] + item["jids"]))
        newer["unread"] = prev["unread"] + item["unread"]
        newer["name"] = newer["name"] or older["name"]
        newer["pic"] = newer["pic"] or older["pic"]
        if newer["jid"].endswith("@s.whatsapp.net") and older["jid"].endswith("@lid"):
            newer["jid"] = older["jid"]  # o @lid é onde as respostas dele chegam
        merged[number] = newer
    out = sorted(merged.values(), key=lambda c: c["ts"], reverse=True)
    return out


@app.get("/api/messages")
async def messages(req: Request, jid: str, page: int = 1, extra: str = ""):
    """`jid` pagina normalmente; `extra` (jids irmãos do mesmo número, vírgula) só página 1 —
    é onde ficam as mensagens que EU mandei, poucas e recentes."""
    _need(req)
    data = await _post(f"/chat/findMessages/{INST}",
                       {"where": {"key": {"remoteJid": jid}}, "limit": 50, "page": page})
    m = data.get("messages") or {}
    recs = list(m.get("records") or [])
    for j in [x for x in extra.split(",") if x and x != jid]:
        d2 = await _post(f"/chat/findMessages/{INST}",
                         {"where": {"key": {"remoteJid": j}}, "limit": 50, "page": 1})
        recs += (d2.get("messages") or {}).get("records") or []
    alt = next((r["key"].get("remoteJidAlt") for r in recs
                if r.get("key", {}).get("remoteJidAlt")), "")
    seen: set[str] = set()
    msgs = []
    for r in recs:
        n = _norm(r)
        if n["id"] in seen:
            continue
        seen.add(n["id"])
        msgs.append(n)
    msgs.sort(key=lambda x: x["ts"])
    return {"messages": msgs, "page": page, "pages": m.get("pages") or 1,
            "number": _number(jid, alt)}


_media: OrderedDict[str, tuple[str, bytes]] = OrderedDict()


async def _fetch_media(jid: str, mid: str) -> tuple[str, bytes]:
    if mid in _media:
        return _media[mid]
    d = await _post(f"/chat/getBase64FromMediaMessage/{INST}",
                    {"message": {"key": {"id": mid, "remoteJid": jid}}, "convertToMp4": False})
    mime = d.get("mimetype") or "application/octet-stream"
    raw = base64.b64decode(d["base64"])
    _media[mid] = (mime, raw)
    while len(_media) > 200:  # ponytail: cache em memória ~200 mídias; Redis se virar gargalo
        _media.popitem(last=False)
    return mime, raw


@app.get("/api/media")
async def media(req: Request, jid: str, id: str):
    _need(req)
    mime, raw = await _fetch_media(jid, id)
    return Response(raw, media_type=mime.split(";")[0], headers={"Cache-Control": "private, max-age=86400"})


@app.post("/api/send")
async def send(req: Request):
    _need(req)
    body = await req.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "texto vazio")
    d = await _post(f"/message/sendText/{INST}", {"number": body["number"], "text": text})
    return {"id": (d.get("key") or {}).get("id"), "status": d.get("status")}


@app.post("/api/read")
async def read(req: Request):
    _need(req)
    body = await req.json()
    items = [{"remoteJid": body["jid"], "fromMe": False, "id": i} for i in body.get("ids") or []]
    if not items:
        return {"ok": True}
    try:
        await _post(f"/chat/markMessageAsRead/{INST}", {"readMessages": items})
    except HTTPException as e:
        return {"ok": False, "err": e.detail}
    return {"ok": True}


_trans: dict[str, str] = {}


@app.post("/api/transcribe")
async def transcribe(req: Request):
    _need(req)
    if not TR_URL:
        raise HTTPException(501, "transcriber não configurado")
    body = await req.json()
    jid, mid = body["jid"], body["id"]
    if mid in _trans:
        return {"texto": _trans[mid]}
    mime, raw = await _fetch_media(jid, mid)
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
                _trans[mid] = txt
                return {"texto": txt}
            await asyncio.sleep(2)
    raise HTTPException(504, "transcrição demorou demais")


@app.get("/healthz")
def healthz():
    return {"ok": True, "instance": INST, "transcriber": bool(TR_URL)}


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML
