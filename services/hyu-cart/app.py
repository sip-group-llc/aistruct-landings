"""
HYU (hyuoficial.com) -> Paggins SDK bridge + CAPTURA DE LEADS (paliativo).

O site e estatico (nginx); este servico:
  1. cria checkout sessions na Paggins (SDK) p/ o carrinho multi-item (sabores + combos).
     Fisico+frete confirmado funcionando 15/06 (scripts/paggins_gate.py; frete GRATIS auto).
  2. confirma pagamento: GET /session (status) + POST /webhook/paggins (eventos -> tabela orders).
  3. captura LEADS (paliativo p/ carrinho abandonado): form -> SQLite no volume da VPS.

POST /frete            <- {cep, items} -> opcoes de frete Mandaê (gratis se >=12 latas)
POST /checkout         <- carrinho {items:[{flavor,tier,qty}|{combo,qty}], meta} -> session
                          + fluxo completo: {customer, address, shipping} -> frete embutido
                          no unitAmount + pedido completo salvo (dados p/ NF-e no Bling)
GET  /session/{id}     <- status do pedido (pro obrigado)
POST /webhook/paggins  <- eventos Paggins (assinatura HMAC) -> marca orders/pedidos pagos
                          -> dispara criacao do pedido de venda no Bling (bling.py)
GET  /login /logout    <- login do painel (cookie HMAC 7d; senha LEADS_PASSWORD)
GET  /pedidos          <- painel HTML dos COMPRADORES (cookie ou Basic) + status Bling
                          (aba "Aguardando" = carrinho abandonado com dados completos;
                          o antigo /leads foi aposentado 06/07 — historico exportado)
GET  /pedidos.xlsx     <- export Excel (openpyxl, mesma auth)
GET  /pedidos.csv      <- export CSV (mesma auth)
POST /pedidos/{id}/bling <- re-tenta criar o pedido no Bling (mesma auth)
GET  /healthz          <- liveness
GET  /                 <- info
GET  /debug/stats      <- contadores

STRIPE (checkout 100% nosso — Payment Element; roda EM PARALELO ao Paggins):
POST /stripe/checkout  <- carrinho + customer/address COMPLETOS (nossa página coleta
                          tudo: CPF/endereço obrigatórios — não há "passo 2" externo)
                          -> cria PaymentIntent (total server-side: catálogo + cupom
                          + frete Mandaê) -> {clientSecret, publishableKey, ...}
POST /stripe/webhook   <- eventos Stripe (assinatura Stripe-Signature) ->
                          payment_intent.succeeded marca pedido pago -> Bling direto
                          (dados já completos; sem enrich)
GET  /stripe/session/{pi} <- status do PaymentIntent (pro /obrigado; PIX = processing)

Env:
  PAGGINS_API_KEY  - sk_live_... — setar no Easypanel, NUNCA no git
  PAGGINS_API_URL  - default https://api.paggins.com
  SITE_BASE        - default https://hyuoficial.com
  PAGGINS_WEBHOOK_SECRET - segredo p/ verificar x-paggins-signature do webhook; NUNCA no git
  LEADS_PASSWORD   - senha do /leads (obrigatoria pro painel; NUNCA no git)
  LEADS_DB         - default /data/leads.db (volume) com fallback ./leads.db
  LOG_LEVEL        - default INFO
  MANDAE_TOKEN     - token da API Mandaê (cálculo de frete) — setar no Easypanel
  MANDAE_CUSTOMER_ID - customerId Mandaê (referência; envio é via Bling)
  BLING_CLIENT_ID / BLING_CLIENT_SECRET / BLING_REFRESH_TOKEN - ver bling.py
  STRIPE_SECRET_KEY / STRIPE_PUBLISHABLE_KEY / STRIPE_WEBHOOK_SECRET - checkout
                     Stripe (sk_test/pk_test em teste); ausentes = rotas /stripe 503
"""
from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import logging
import os
import re
import secrets
import sqlite3
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncio
import time

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

from bling import BlingClient, BlingError
import shopify_store

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hyu-cart")

PAGGINS_API_KEY = os.environ.get("PAGGINS_API_KEY", "").strip()
PAGGINS_API_URL = os.environ.get("PAGGINS_API_URL", "https://api.paggins.com").rstrip("/")
SITE_BASE = os.environ.get("SITE_BASE", "https://hyuoficial.com").rstrip("/")
# email placeholder p/ a SDK Paggins (customer.email virou obrigatorio 24/06) — editavel no checkout
PLACEHOLDER_EMAIL = os.environ.get("CHECKOUT_PLACEHOLDER_EMAIL", "comprador@hyuoficial.com").strip()
# domínios do HYU (CORS + success/cancel por origem) — hyudrinks.com é o principal
HYU_ORIGINS = [
    "https://hyudrinks.com", "https://www.hyudrinks.com",
    "https://hyuoficial.com", "https://www.hyuoficial.com",
    "https://teste.hyuoficial.com",  # site de teste (checkout Shopify gateado)
]
LEADS_PASSWORD = os.environ.get("LEADS_PASSWORD", "").strip()
PAGGINS_WEBHOOK_SECRET = os.environ.get("PAGGINS_WEBHOOK_SECRET", "").strip()
LEADS_DB = os.environ.get("LEADS_DB", "/data/leads.db")
# afiliados: % default de comissao sobre o SUBTOTAL de produtos (sem frete, pos-cupom)
AFILIADO_PCT = float(os.environ.get("AFILIADO_PCT", "5") or 5)
MANDAE_TOKEN = os.environ.get("MANDAE_TOKEN", "").strip()
MANDAE_RATES_URL = "https://api.mandae.com.br/v2/postalcodes/{cep}/rates"
FREE_SHIPPING_CANS = 12          # política: frete grátis a partir de 12 latas
# frete FLAT do kit6 (<12 latas) no fluxo simples/drawer (sem endereço p/ cotar Mandaê).
# ≥12 latas = grátis. Necessário porque o checkout SDK da Paggins IGNORA as regras de
# frete por-produto e usa só o "frete geral" (que deixamos em 0) — então a diferenciação
# kit6-pago / acima-grátis é feita aqui, embutindo no preço. 0 = desliga (volta a tudo grátis).
FLAT_SHIPPING_CENTS = int(os.environ.get("FLAT_SHIPPING_CENTS", "3377"))  # R$ 33,77 = média total nacional Mandaê (27 capitais, Econômico+Rápido)
# o frete vai como um ITEM separado "Frete" no checkout (linha própria; a Paggins
# mostra envio "Grátis" pois já está contabilizado). Reusa um productId Paggins real
# (name/unitAmount são sobrescritos por sessão) — trocar por SKU dedicado quando criado.
FRETE_PRODUCT_ID = os.environ.get(
    "FRETE_PRODUCT_ID", "9dfc2557-bf1d-4a15-9988-d705dcbbe8f8")
BLING = BlingClient()


# ── Cupons de influencer (desconto aplicado AQUI, no unitAmount) ──────────────
# O checkout EXTERNO (SDK) da Paggins NÃO aplica cupom (provado: campo de cupom não
# funciona em sessões SDK). Então o desconto é aplicado no preço que enviamos, e o
# código do influencer vai em metadata.coupon p/ atribuição/comissão.
# Override por env: INFLUENCER_COUPONS_JSON='{"ARTHURPC":5,...}'
_DEFAULT_COUPONS = {
    "ARTHURPC": 5, "THIAGO": 5, "ISA": 5, "NATHAN": 5, "DIGAO": 5,
    "KAKAU": 10, "BVELOSO": 10, "THIAGOC": 10,
    "COSENZA10": 10, "RD10": 10,
}


def _parse_coupons() -> dict[str, int]:
    raw = os.environ.get("INFLUENCER_COUPONS_JSON", "").strip()
    if raw:
        try:
            return {str(k).strip().upper(): int(v) for k, v in json.loads(raw).items()
                    if 0 < int(v) < 100}
        except Exception:
            logging.getLogger("hyu-cart").error("INFLUENCER_COUPONS_JSON invalido; usando default")
    return dict(_DEFAULT_COUPONS)


INFLUENCER_COUPONS = _parse_coupons()


def _coupon_discount(raw_coupon: Any) -> tuple[str, int]:
    """Retorna (CODIGO, pct) se o cupom for válido/conhecido, senão ("", 0)."""
    code = str(raw_coupon or "").strip().upper()
    if code and code.isalnum() and code in INFLUENCER_COUPONS:
        return code, INFLUENCER_COUPONS[code]
    return "", 0
if not os.path.isdir(os.path.dirname(LEADS_DB) or "."):
    LEADS_DB = "./leads.db"  # dev local sem volume

app = FastAPI(title="HYU cart -> Paggins bridge", version="1.6.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=HYU_ORIGINS + [
        "https://hyuoficial.tiectu.easypanel.host",
        "http://localhost:4321", "http://localhost:4322", "http://localhost:4323",
        "http://127.0.0.1:4321", "http://127.0.0.1:4322", "http://127.0.0.1:4323",
    ],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Content-Type"],
)

# ── catalogo server-side (fonte da verdade de preco/nome) ───────────────
# productId = UUID do produto na Paggins. ⚠️ os PREÇOS (cents) DEVEM casar com o
# front (src/data/products.ts: prices/combos). Hoje: kit6=6990 kit12=11990 kit24=21990 sub=9990.
FLAVORS: dict[str, dict[str, str]] = {
    "hot-lemon":       {"name": "HYU Soda Protein Hot Lemon", "sku": "HOTLEMON",
                        "short": "Hot Lemon", "code": "HL",
                        "desc": "15g de proteína · 3g de fibras · zero açúcar · 269ml"},
    "maca-verde":      {"name": "HYU Soda Protein Maçã Verde", "sku": "MACAVERDE",
                        "short": "Maçã Verde", "code": "MV",
                        "desc": "15g de proteína · 3g de fibras · zero açúcar · 269ml"},
    "pessego-morango": {"name": "HYU Soda Protein Pêssego com Morango", "sku": "PESSEGOMORANGO",
                        "short": "Pêssego com Morango", "code": "PM",
                        "desc": "15g de proteína · 3g de fibras · zero açúcar · 269ml"},
    "tropical":        {"name": "HYU Energy Protein Tropical", "sku": "TROPICAL",
                        "short": "Tropical", "code": "TP",
                        "desc": "15g de proteína · 85mg de cafeína natural · zero açúcar · 269ml"},
    "maca-vermelha":   {"name": "HYU Energy Protein Maçã Vermelha", "sku": "MACAVERMELHA",
                        "short": "Maçã Vermelha", "code": "MA",
                        "desc": "15g de proteína · 85mg de cafeína natural · zero açúcar · 269ml"},
}
TIERS: dict[str, dict[str, Any]] = {
    "kit6":  {"label": "Kit 6 (6 latas)",   "cents": 6990,  "sku": "K6",  "cans": 6},
    "kit12": {"label": "Kit 12 (12 latas)", "cents": 11990, "sku": "K12", "cans": 12},
}
PRODUCT_IDS: dict[tuple[str, str], str] = {
    ("hot-lemon", "kit6"):        "8534bbc5-5a43-46e2-9551-89d26d84c22f",
    ("hot-lemon", "kit12"):       "95e0f88f-6fca-4a19-89a1-9583c93e09df",
    ("maca-verde", "kit6"):       "a585f927-16c4-47ae-a13b-980b3c55601e",
    ("maca-verde", "kit12"):      "909baad1-bd89-4e28-ab14-4f3793fbabea",
    ("pessego-morango", "kit6"):  "1cf46530-8d6a-4feb-a1c9-cacfd0b93481",
    ("pessego-morango", "kit12"): "7ff35585-7f89-4c11-b67a-b564e601a820",
    ("tropical", "kit6"):         "e3fc8cae-ed54-4b22-8d67-2e914eadb14e",
    ("tropical", "kit12"):        "ee27af7e-cc0f-4212-b162-692776fd7f09",
    ("maca-vermelha", "kit6"):    "6595de07-23c2-44b7-bf99-d2f00919be96",
    ("maca-vermelha", "kit12"):   "d8d1b025-bb9f-4b80-92c0-76845a01453c",
}
# ── kit PERSONALIZADO (mix de sabores lata a lata) ───────────────────────────
# Item do carrinho: {mix:{slug:latas,...}, tier, qty}. A soma das latas DEVE fechar
# o kit (6 ou 12). Preço = kit + taxa de personalização. Mix de 1 sabor só colapsa
# pra kit normal SEM taxa. A composição vai no NAME (único campo que a Paggins
# renderiza) e no SKU (fulfillment lê a receita: HYU-MIXK6-MA3TP2HL1).
# productId: reusa um produto Paggins existente (name/unitAmount são sobrescritos
# por sessão — mesmo padrão provado do cupom/frete embutido). Trocar por produto
# dedicado quando criado no painel: MIX_PRODUCT_ID_KIT6 / MIX_PRODUCT_ID_KIT12.
MIX_FEE_CENTS = int(os.environ.get("MIX_FEE_CENTS", "490"))   # R$4,90 por kit — manter = front (cart.hyumix)
MIX_STEP = int(os.environ.get("MIX_STEP", "1"))                # latas por sabor: 1 = escolha livre — manter = front
# sabores SEM ESTOQUE (tarja "Em breve" no site): bloqueia kit por sabor e mix que
# os contenha. Voltar estoque = setar env vazio ("") + tirar a tarja do front.
# ⚠️ COMBOS que contêm esses sabores (kit-soda/super-kit/kit24/assinaturas) seguem
# vendendo — decisão de negócio separada.
OUT_OF_STOCK = {s.strip() for s in os.environ.get(
    "OUT_OF_STOCK_FLAVORS", "hot-lemon,pessego-morango").split(",") if s.strip()}
MIX_PRODUCT_IDS: dict[str, str] = {
    "kit6":  os.environ.get("MIX_PRODUCT_ID_KIT6",
                            "62ed2805-089e-454f-afa0-f28f6dfa6abc"),   # HYU Kit Soda (6)
    "kit12": os.environ.get("MIX_PRODUCT_ID_KIT12",
                            "972ac99f-2800-4db9-88af-d34246cbd3ed"),   # HYU Super Kit (12)
}

# combos = produtos Paggins proprios (1 productId cada). Assinaturas NAO entram (links fixos).
COMBOS: dict[str, dict[str, Any]] = {
    "kit-energy": {"productId": "5287a35b-9a4c-4307-a929-599ab5e2791d", "cents": 6990,
                   "name": "HYU Kit Energy (6 latas)", "sku": "KITENERGY", "img": "kit-energy",
                   "cans": 6},
    "kit-soda":   {"productId": "62ed2805-089e-454f-afa0-f28f6dfa6abc", "cents": 6990,
                   "name": "HYU Kit Soda (6 latas)", "sku": "KITSODA", "img": "kit-soda",
                   "cans": 6},
    "super-kit":  {"productId": "972ac99f-2800-4db9-88af-d34246cbd3ed", "cents": 11990,
                   "name": "HYU Super Kit (12 latas)", "sku": "SUPERKIT", "img": "super-kit",
                   "cans": 12},
    "kit24":      {"productId": "35818f74-5267-46d6-98f7-c19badd7cea7", "cents": 21990,
                   "name": "HYU Kit 24 (24 latas)", "sku": "KIT24", "img": "super-kit",
                   "cans": 24},
}

# ── frete Mandaê ──────────────────────────────────────────────────────────────
# Peso/caixa por faixa de latas (lata 269ml cheia ~300g + caixa). Kit 6 cai na
# faixa 1501-2000g da tabela Mandaê (planilha FontesLog). Limites Mandaê:
# 120cm/lado, 50kg, valor declarado R$5.000.
def _package_for(cans: int) -> dict[str, float]:
    if cans <= 6:
        return {"weight": 1.9, "height": 13, "width": 17, "length": 25}
    if cans <= 12:
        return {"weight": 3.8, "height": 14, "width": 25, "length": 33}
    if cans <= 24:
        return {"weight": 7.5, "height": 15, "width": 33, "length": 40}
    return {"weight": min(round(0.31 * cans + 0.3, 1), 50.0),
            "height": 30, "width": 33, "length": 40}


_FRETE_CACHE: dict[tuple, tuple[float, list[dict[str, Any]]]] = {}
_FRETE_TTL = 600  # 10min


async def _mandae_rates(cep: str, cans: int, declared_cents: int) -> list[dict[str, Any]]:
    """Cota na Mandaê; retorna [{service, name, days, cents}] (Econômico/Rápido)."""
    if not MANDAE_TOKEN:
        raise HTTPException(503, "frete indisponivel (MANDAE_TOKEN ausente)")
    key = (cep, min(cans, 48), min(declared_cents // 10000, 50))
    hit = _FRETE_CACHE.get(key)
    if hit and time.time() - hit[0] < _FRETE_TTL:
        return hit[1]
    body = dict(_package_for(cans))
    body["declaredValue"] = min(declared_cents / 100, 5000.0)
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(MANDAE_RATES_URL.format(cep=cep),
                             headers={"Authorization": MANDAE_TOKEN,
                                      "Content-Type": "application/json"},
                             json=body)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"mandae indisponivel: {str(e)[:80]}")
    if r.status_code != 200:
        log.error("mandae %s cep=%s: %s", r.status_code, cep, r.text[:200])
        raise HTTPException(502, "cotacao de frete falhou")
    services = (r.json() or {}).get("shippingServices") or []
    options = []
    for s in services:
        name = str(s.get("name", "")).strip()
        slug = ("economico" if "econ" in name.lower()
                else "rapido" if "ráp" in name.lower() or "rap" in name.lower()
                else name.lower()[:20])
        options.append({"service": slug, "name": name,
                        "days": int(s.get("days") or 0),
                        "cents": int(round(float(s.get("price") or 0) * 100))})
    if not options:
        raise HTTPException(502, "mandae sem opcoes p/ este CEP")
    _FRETE_CACHE[key] = (time.time(), options)
    if len(_FRETE_CACHE) > 500:  # poda simples
        for k in list(_FRETE_CACHE)[:100]:
            _FRETE_CACHE.pop(k, None)
    return options

MAX_LINES = 10      # combinacoes distintas por pedido
MAX_QTY = 20        # kits por linha
META_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_term",
             "utm_content", "gclid", "fbclid", "ref", "src")

RECENT: deque = deque(maxlen=80)
STATS = {"received": 0, "created": 0, "bad_request": 0, "paggins_error": 0,
         "leads_received": 0, "leads_saved": 0, "leads_bad": 0,
         "webhook_received": 0, "webhook_paid": 0, "webhook_bad_sig": 0}

# ── leads: SQLite no volume da VPS ───────────────────────────────────
def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(LEADS_DB)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS leads ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, name TEXT, email TEXT, "
        "phone TEXT, pedido TEXT, total_cents INTEGER, items TEXT, meta TEXT, "
        "ip TEXT, ua TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS orders ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, session_id TEXT, order_id TEXT, "
        "event TEXT, status TEXT, amount_cents INTEGER, verified INTEGER, payload TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS pedidos ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, order_id TEXT, session_id TEXT, "
        "status TEXT, paid_ts TEXT, "
        "name TEXT, document TEXT, email TEXT, phone TEXT, "
        "cep TEXT, street TEXT, number TEXT, complement TEXT, neighborhood TEXT, "
        "city TEXT, state TEXT, "
        "items TEXT, subtotal_cents INTEGER, frete_cents INTEGER, frete_service TEXT, "
        "total_cents INTEGER, coupon TEXT, meta TEXT, "
        "bling_status TEXT, bling_order_id TEXT, bling_error TEXT, tracking TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS afiliados ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, tag TEXT UNIQUE, name TEXT, "
        "email TEXT, phone TEXT, pix TEXT, pct REAL, token TEXT, active INTEGER DEFAULT 1)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS comissoes ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, tag TEXT, pedido_id INTEGER, "
        "order_id TEXT UNIQUE, base_cents INTEGER, pct REAL, valor_cents INTEGER, "
        "status TEXT, paid_ts TEXT)"
    )
    # migracoes leves (tabelas ja criadas em producao nao ganham coluna via CREATE IF NOT EXISTS)
    for tbl, col, decl in (("afiliados", "cupom", "TEXT"), ("comissoes", "via", "TEXT")):
        try:
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {decl}")
        except sqlite3.OperationalError:
            pass  # ja existe
    return conn


def _cart_lines(raw_items: Any) -> list[dict[str, Any]]:
    """Valida/mescla o carrinho; retorna linhas normalizadas com preco do catalogo:
    [{qty, sku, name, cents, cans, productId, img, desc?}] (cents = unitario)."""
    if not isinstance(raw_items, list) or not raw_items:
        raise HTTPException(400, "items vazio")
    merged: dict[tuple, int] = {}
    for it in raw_items:
        if not isinstance(it, dict):
            raise HTTPException(400, "item invalido")
        try:
            qty = int(it.get("qty", 1))
        except (TypeError, ValueError):
            raise HTTPException(400, "qty invalida")
        if not 1 <= qty <= MAX_QTY:
            raise HTTPException(400, f"qty fora de 1..{MAX_QTY}")
        combo = it.get("combo")
        mix = it.get("mix")
        if combo is not None:
            if combo not in COMBOS:
                raise HTTPException(400, f"combo desconhecido: {combo}")
            key: tuple = ("combo", combo)
        elif mix is not None:
            tier = it.get("tier")
            if tier not in TIERS:
                raise HTTPException(400, f"tier de mix desconhecido: {tier}")
            if not isinstance(mix, dict) or not mix:
                raise HTTPException(400, "mix invalido")
            counts: dict[str, int] = {}
            for slug, n in mix.items():
                if slug not in FLAVORS:
                    raise HTTPException(400, f"sabor desconhecido no mix: {slug}")
                if slug in OUT_OF_STOCK:
                    raise HTTPException(
                        400, f"{FLAVORS[slug]['short']} esgotado — em breve de volta; "
                             "tira ele do kit pra continuar")
                try:
                    n = int(n)
                except (TypeError, ValueError):
                    raise HTTPException(400, "mix com quantidade invalida")
                if n < 1:
                    raise HTTPException(400, "mix com quantidade invalida")
                if n % MIX_STEP:
                    raise HTTPException(
                        400, f"mix em multiplos de {MIX_STEP} latas por sabor "
                             f"({slug}={n})")
                counts[slug] = counts.get(slug, 0) + n
            if sum(counts.values()) != TIERS[tier]["cans"]:
                raise HTTPException(
                    400, f"mix nao fecha o kit: soma {sum(counts.values())} != "
                         f"{TIERS[tier]['cans']} latas ({tier})")
            if len(counts) == 1:
                # 1 sabor só = kit normal (sem taxa de personalização)
                key = ("flavor", next(iter(counts)), tier)
            else:
                key = ("mix", tier, tuple(sorted(counts.items())))
        else:
            flavor, tier = it.get("flavor"), it.get("tier")
            if flavor not in FLAVORS or tier not in TIERS:
                raise HTTPException(400, f"combinacao desconhecida: {flavor}/{tier}")
            if flavor in OUT_OF_STOCK:
                raise HTTPException(
                    400, f"{FLAVORS[flavor]['short']} esgotado — em breve de volta; "
                         "tira ele da sacola pra continuar")
            key = ("flavor", flavor, tier)
        merged[key] = min(merged.get(key, 0) + qty, MAX_QTY)
    if len(merged) > MAX_LINES:
        raise HTTPException(400, f"mais de {MAX_LINES} combinacoes")
    lines = []
    for key, qty in merged.items():
        if key[0] == "combo":
            c = COMBOS[key[1]]
            lines.append({"qty": qty, "sku": f"HYU-{c['sku']}", "name": c["name"],
                          "cents": c["cents"], "cans": c["cans"] * qty,
                          "productId": c["productId"], "img": c["img"]})
        elif key[0] == "mix":
            _, tier, comp = key
            t = TIERS[tier]
            # composição: mais latas primeiro (desempate por nome estável)
            ordered = sorted(comp, key=lambda kv: (-kv[1], kv[0]))
            comp_txt = " + ".join(f"{n} {FLAVORS[s]['short']}" for s, n in ordered)
            kit_lbl = t["label"].split(" (")[0]          # "Kit 6"
            lines.append({
                "qty": qty,
                "sku": "HYU-MIX" + t["sku"] + "-"
                       + "".join(f"{FLAVORS[s]['code']}{n}" for s, n in ordered),
                "name": f"HYU {kit_lbl} Personalizado — {comp_txt}",
                "cents": t["cents"] + MIX_FEE_CENTS,
                "cans": t["cans"] * qty,
                "productId": MIX_PRODUCT_IDS[tier],
                "img": "super-kit",
                "desc": "Kit montado lata a lata pelo cliente "
                        "(taxa de personalização inclusa)",
            })
        else:
            _, flavor, tier = key
            f, t = FLAVORS[flavor], TIERS[tier]
            lines.append({"qty": qty, "sku": f"HYU-{f['sku']}-{t['sku']}",
                          "name": f"{f['name']} — {t['label']}", "cents": t["cents"],
                          "cans": t["cans"] * qty,
                          "productId": PRODUCT_IDS[(flavor, tier)],
                          "img": flavor, "desc": f["desc"]})
    return lines


def _build_items(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Monta os items da Paggins a partir das linhas normalizadas."""
    items = []
    for ln in lines:
        base = {
            "productId": ln["productId"], "name": ln["name"], "type": "physical",
            "unitAmount": ln["cents"], "quantity": 1, "sku": ln["sku"],
            "imageUrl": f"{SITE_BASE}/img/kits/{ln['img']}.webp",
        }
        if ln.get("desc"):
            base["description"] = ln["desc"]
        # ⚠️ SDK Paggins exige quantity=1 por item → duplica a entrada `qty` vezes
        items.extend(dict(base) for _ in range(ln["qty"]))
    return items


def _build_metadata(raw_meta: Any) -> dict[str, str]:
    if not isinstance(raw_meta, dict):
        return {}
    return {k: str(raw_meta[k])[:200] for k in META_KEYS if raw_meta.get(k)}


def _valid_cpf(doc: str) -> bool:
    d = re.sub(r"\D", "", doc)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        s = sum(int(d[i]) * ((n + 1) - i) for i in range(n))
        dv = (s * 10) % 11 % 10
        if dv != int(d[n]):
            return False
    return True


def _parse_customer_address(payload: dict) -> tuple[dict, dict] | tuple[None, None]:
    """Extrai/valida customer+address do fluxo completo; (None, None) = fluxo legado.

    Passo-1 enxuto (desde 07/07): o site coleta só nome/celular/e-mail + CEP.
    CPF e endereço completo são OPCIONAIS aqui — a Paggins coleta no passo 2 e o
    webhook enriquece o pedido (GET session) pra NF-e. Payload antigo (com tudo)
    continua aceito."""
    cust, addr = payload.get("customer"), payload.get("address")
    if not (isinstance(cust, dict) and isinstance(addr, dict) and addr.get("cep")):
        return None, None
    name = str(cust.get("name", "")).strip()[:120]
    document = re.sub(r"\D", "", str(cust.get("document", "")))
    email = str(cust.get("email", "")).strip()[:160].lower()
    phone = re.sub(r"\D", "", str(cust.get("phone", "")))[:13]
    if len(name.split()) < 2:
        raise HTTPException(400, "nome completo obrigatorio")
    if document and not _valid_cpf(document):
        raise HTTPException(400, "CPF invalido")
    if not _EMAIL_RE.match(email):
        raise HTTPException(400, "e-mail invalido")
    if phone and not _PHONE_RE.match(phone):
        raise HTTPException(400, "whatsapp invalido (DDD + numero)")
    cep = re.sub(r"\D", "", str(addr.get("cep", "")))
    if len(cep) != 8:
        raise HTTPException(400, "CEP invalido")
    street = str(addr.get("street", "")).strip()[:120]
    number = str(addr.get("number", "")).strip()[:12]
    city = str(addr.get("city", "")).strip()[:80]
    state = str(addr.get("state", "")).strip()[:2].upper()
    if (street or number or city or state) and not (street and number and city and len(state) == 2):
        raise HTTPException(400, "endereco incompleto (rua/numero/cidade/UF)")
    return (
        {"name": name, "document": document, "email": email, "phone": phone},
        {"cep": cep, "street": street, "number": number,
         "complement": str(addr.get("complement", "")).strip()[:100],
         "neighborhood": str(addr.get("neighborhood", "")).strip()[:80],
         "city": city, "state": state},
    )


@app.post("/frete")
async def cotar_frete(request: Request):
    """Cotação Mandaê pro carrinho: {cep, items} -> opções (grátis se >=12 latas)."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "JSON invalido")
    cep = re.sub(r"\D", "", str(payload.get("cep", "")))
    if len(cep) != 8:
        raise HTTPException(400, "CEP invalido")
    lines = _cart_lines(payload.get("items"))
    cans = sum(ln["cans"] for ln in lines)
    subtotal = sum(ln["cents"] * ln["qty"] for ln in lines)
    free = cans >= FREE_SHIPPING_CANS
    try:
        options = await _mandae_rates(cep, cans, subtotal)
        if free:
            options = [{**o, "cents": 0} for o in options]
    except HTTPException:
        # frete GRÁTIS (>=12 latas) não depende da Mandaê — não deixa a cotação
        # indisponível travar a loja. Kit 6 avulso (pago) ainda exige a Mandaê.
        if not free:
            raise
        options = [{"service": "economico", "name": "Frete Grátis",
                    "days": 7, "cents": 0}]
    return {"cep": cep, "cans": cans, "free": free, "options": options}


@app.post("/checkout")
async def create_checkout(request: Request):
    try:
        payload = await request.json()
    except Exception:
        STATS["received"] += 1
        STATS["bad_request"] += 1
        raise HTTPException(400, "JSON invalido")
    return await _do_checkout(payload)


@app.get("/buy")
async def buy(request: Request):
    """Link de compra DIRETO p/ anúncios/bio (external): cria a sessão pelo bridge
    — frete correto (< 12 latas paga, >= 12 grátis) e nome correto — e redireciona
    pro checkout. Use ISTO em vez do link cru paggins.com/checkout/<uuid> (que não
    passa pelo bridge e sai grátis). Exemplos:
      /buy?combo=kit-soda
      /buy?flavor=tropical&tier=kit6&qty=1
      /buy?combo=super-kit&utm_source=ig&utm_campaign=x [&coupon=ARTHURPC]"""
    from fastapi.responses import RedirectResponse
    q = request.query_params
    combo, flavor, tier = q.get("combo"), q.get("flavor"), q.get("tier")
    if combo:
        item: dict = {"combo": combo}
    elif flavor and tier:
        item = {"flavor": flavor, "tier": tier}
    else:
        raise HTTPException(400, "informe ?combo=<slug> ou ?flavor=<sabor>&tier=<kit6|kit12>")
    try:
        item["qty"] = max(1, min(int(q.get("qty", 1)), MAX_QTY))
    except (TypeError, ValueError):
        item["qty"] = 1
    payload = {"items": [item], "origin": q.get("origin") or SITE_BASE,
               "meta": {k: q[k] for k in META_KEYS if q.get(k)}}
    if q.get("coupon"):
        payload["coupon"] = q["coupon"]
    res = await _do_checkout(payload)
    url = res.get("checkoutUrl")
    if not url:
        raise HTTPException(502, "checkout indisponivel")
    return RedirectResponse(url, status_code=302)


async def _do_checkout(payload: dict) -> dict:
    STATS["received"] += 1
    try:
        lines = _cart_lines(payload.get("items"))
        customer, address = _parse_customer_address(payload)
    except HTTPException:
        STATS["bad_request"] += 1
        raise
    items = _build_items(lines)
    subtotal = sum(ln["cents"] * ln["qty"] for ln in lines)
    cans = sum(ln["cans"] for ln in lines)

    # cupom de influencer → desconta o unitAmount de cada item (centavos, arredonda)
    coupon_code, discount_pct = _coupon_discount(payload.get("coupon"))
    if discount_pct:
        # half-up em centavos inteiros — bate exatamente com o display do front (JS Math.round)
        # + selo no NOME (único campo que renderiza no resumo da Paggins; description/linha
        #   negativa/item R$0 são rejeitados) p/ o cliente ver que o desconto já está aplicado.
        #   O SKU permanece limpo (fulfillment lê o SKU).
        tag = f" · {discount_pct}% OFF cupom {coupon_code}"
        for it in items:
            it["unitAmount"] = max(1, (it["unitAmount"] * (100 - discount_pct) + 50) // 100)
            it["name"] = (str(it.get("name", ""))[:255 - len(tag)] + tag)

    # ── FRETE decidido AQUI (NÃO usamos o frete nativo da Paggins: o checkout SDK
    #    ignora as regras por-produto e o "frete geral" da loja fica em 0). O frete
    #    vai como um ITEM SEPARADO "Frete" → aparece como linha própria no resumo e
    #    a Paggins mostra envio "Grátis" (já contabilizado no item).
    #    Regra POR TOTAL DE LATAS: pedido com < 12 latas (= 1 kit6) paga frete;
    #    a partir de 12 latas (2× kit6, kit12, super-kit, kit24, assinatura) = grátis.
    frete_cents, frete_service = 0, ""
    below_free = cans < FREE_SHIPPING_CANS
    if not below_free:
        frete_service = "gratis"
    elif customer and address:
        # fluxo completo (pré-checkout com endereço): frete REAL por CEP (Mandaê)
        options = await _mandae_rates(address["cep"], cans, subtotal)
        wanted = str((payload.get("shipping") or {}).get("service") or "economico")
        opt = next((o for o in options if o["service"] == wanted), options[0])
        frete_cents, frete_service = opt["cents"], opt["service"]
    elif FLAT_SHIPPING_CENTS > 0:
        # fluxo simples (drawer, sem endereço): frete FLAT
        frete_cents, frete_service = FLAT_SHIPPING_CENTS, "flat"
    if frete_cents > 0:
        items.append({
            "productId": FRETE_PRODUCT_ID, "name": "Frete", "type": "physical",
            "unitAmount": frete_cents, "quantity": 1, "sku": "HYU-FRETE",
            "imageUrl": f"{SITE_BASE}/img/frete.webp",
        })

    order_id = f"hyu-{uuid.uuid4().hex[:12]}"
    origin = str(payload.get("origin") or "").rstrip("/")
    base = origin if origin in HYU_ORIGINS else SITE_BASE  # volta pro domínio de origem
    # ⚠️ a SDK Paggins passou a EXIGIR customer.email valido (24/06; ainda "optional" na doc) —
    # sem ele toda sessao volta 400 "Dados da requisicao sao invalidos". No fluxo legado o
    # site nao coleta email antes do checkout → placeholder editavel na pagina da Paggins.
    # No fluxo completo o pré-checkout coleta o email real (validado).
    cust_email = str((customer or payload.get("customer") or {}).get("email") or "").strip()
    if not _EMAIL_RE.match(cust_email):
        cust_email = PLACEHOLDER_EMAIL
    pag_customer: dict[str, str] = {"email": cust_email}
    if customer:
        pag_customer["name"] = customer["name"]
        # ⚠️ phone NÃO vai no customer: o create-session RECUSA (400) em qualquer
        # formato (provado 07/07, scripts/paggins_phone_probe.py — a doc mente).
        # O prefill do telefone vai por query param no checkoutUrl (doc
        # "Parâmetros da URL de Checkout", 07/07).
    body = {
        "currency": "BRL",
        "items": items,
        # ⚠️ SEMPRE true p/ produto físico. Com false a Paggins CRIA a sessão mas
        # RECUSA o pagamento ("Endereço de entrega é obrigatório quando há produtos
        # físicos") — é o "beco sem saída" da lesson paggins.md. O cliente reconfirma
        # o endereço na Paggins; nós já temos o dado salvo p/ a NF-e no Bling.
        "requireShippingInfo": True,
        # ref = nosso order_id (SEMPRE correto). session_id usa o placeholder da
        # Paggins ({CHECKOUT_SESSION_ID}) — se ela não substituir, a página usa a ref.
        "successUrl": f"{base}/obrigado/?ref={order_id}&session_id={{CHECKOUT_SESSION_ID}}",
        "cancelUrl": f"{base}/?checkout=cancelado",
        "externalOrderId": order_id,
        "customer": pag_customer,
    }
    metadata = _build_metadata(payload.get("meta"))
    if discount_pct:
        metadata["coupon"] = coupon_code
        metadata["discount_pct"] = str(discount_pct)
    if metadata:
        body["metadata"] = metadata

    headers = {
        "Authorization": f"Bearer {PAGGINS_API_KEY}",
        "Content-Type": "application/json",
        "Idempotency-Key": str(uuid.uuid4()),
    }
    # 1 retry em erro de rede/5xx — mesma Idempotency-Key garante que nao duplica
    last_err = "?"
    for attempt in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(f"{PAGGINS_API_URL}/v1/sdk/checkout-sessions",
                                 headers=headers, json=body)
            if r.status_code in (200, 201):
                sess = r.json()
                total = sum(i["unitAmount"] * i["quantity"] for i in items)
                STATS["created"] += 1
                RECENT.append({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "order_id": order_id, "session_id": sess.get("id"),
                    "lines": [(i["sku"], i["quantity"]) for i in items],
                    "total": total, "meta": list(metadata),
                })
                if customer:
                    # pedido completo (dados p/ NF-e) — casado depois pelo webhook
                    conn = _db()
                    try:
                        conn.execute(
                            "INSERT INTO pedidos (ts, order_id, session_id, status, "
                            "name, document, email, phone, cep, street, number, "
                            "complement, neighborhood, city, state, items, "
                            "subtotal_cents, frete_cents, frete_service, total_cents, "
                            "coupon, meta, bling_status) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             order_id, sess.get("id"), "created",
                             customer["name"], customer["document"],
                             customer["email"], customer["phone"],
                             address["cep"], address["street"], address["number"],
                             address["complement"], address["neighborhood"],
                             address["city"], address["state"],
                             json.dumps([{k: ln[k] for k in
                                          ("sku", "name", "qty", "cents", "cans")}
                                         for ln in lines], ensure_ascii=False),
                             subtotal, frete_cents, frete_service, total,
                             coupon_code, json.dumps(metadata, ensure_ascii=False),
                             ""))
                        conn.commit()
                    finally:
                        conn.close()
                log.info("checkout %s -> %s total=%s frete=%s/%s coupon=%s", order_id,
                         sess.get("id"), total, frete_service or "-", frete_cents,
                         coupon_code or "-")
                # prefill do telefone no passo 2 via query param (?phone=+55…)
                checkout_url = sess.get("checkoutUrl") or ""
                ph = re.sub(r"\D", "", (customer or {}).get("phone") or "")
                if checkout_url and 10 <= len(ph) <= 11:
                    sep = "&" if "?" in checkout_url else "?"
                    checkout_url += f"{sep}phone=%2B55{ph}"
                return {"checkoutUrl": checkout_url,
                        "sessionId": sess.get("id"), "totalAmount": total,
                        "freteCents": frete_cents, "freteService": frete_service,
                        "coupon": coupon_code, "discountPct": discount_pct}
            if r.status_code < 500:
                STATS["paggins_error"] += 1
                log.error("paggins %s: %s", r.status_code, r.text[:300])
                raise HTTPException(502, "checkout indisponivel")
            last_err = f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            last_err = str(e)[:120]
        log.warning("tentativa %d falhou (%s)", attempt, last_err)
    STATS["paggins_error"] += 1
    raise HTTPException(502, "checkout indisponivel")


@app.get("/session/{session_id}")
async def get_session(session_id: str):
    """Confirma o status do pedido (usado pelo obrigado.astro)."""
    if not re.match(r"^cs_[A-Za-z0-9]+$", session_id):
        raise HTTPException(400, "session_id invalido")
    headers = {"Authorization": f"Bearer {PAGGINS_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(
                f"{PAGGINS_API_URL}/v1/sdk/checkout-sessions/{session_id}?countryCode=BR",
                headers=headers)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"paggins indisponivel: {str(e)[:80]}")
    if r.status_code == 404:
        raise HTTPException(404, "sessao nao encontrada")
    if r.status_code != 200:
        raise HTTPException(502, f"paggins {r.status_code}")
    s = r.json()
    pay = s.get("payment") or {}
    return {"id": s.get("id"), "status": s.get("status"),
            "paymentStatus": pay.get("status"), "totalAmount": s.get("totalAmount"),
            "currency": s.get("currency")}


def _webhook_verified(raw: bytes, sig: str) -> bool:
    """Confere a assinatura HMAC-SHA256 tentando variações de chave/payload
    (com/sem prefixo whsec_, raw vs JSON compacto) — o esquema exato é confirmado
    no 1º webhook real."""
    if not (PAGGINS_WEBHOOK_SECRET and sig):
        return False
    keys = {PAGGINS_WEBHOOK_SECRET}
    if "_" in PAGGINS_WEBHOOK_SECRET:
        keys.add(PAGGINS_WEBHOOK_SECRET.split("_", 1)[1])
    bodies = {raw}
    try:
        bodies.add(json.dumps(json.loads(raw), separators=(",", ":")).encode())
    except Exception:
        pass
    for k in keys:
        for b in bodies:
            if hmac.compare_digest(hmac.new(k.encode(), b, hashlib.sha256).hexdigest(), sig):
                return True
    return False


@app.post("/webhook/paggins")
async def paggins_webhook(request: Request):
    """Recebe eventos da Paggins e marca pedidos pagos. Verifica a assinatura HMAC
    mas NÃO descarta em mismatch — registra `verified` e processa mesmo assim, pra
    não perder pedido caso o esquema de assinatura difira (apertar após o 1º real)."""
    raw = await request.body()
    STATS["webhook_received"] += 1
    verified = _webhook_verified(raw, request.headers.get("x-paggins-signature", ""))
    if not verified:
        STATS["webhook_bad_sig"] += 1
    try:
        ev = json.loads(raw or b"{}")
    except Exception:
        raise HTTPException(400, "JSON invalido")
    event = ev.get("event") or ev.get("type") or ""
    sid = ev.get("sessionId") or ev.get("session_id") or ""
    PAID = {"checkout.session.completed", "payment.succeeded", "order.fulfilled"}
    if event in PAID:
        pay = ev.get("payment") or {}
        order_id = ev.get("orderId") or ev.get("externalOrderId") or ""
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        pedido_id = None
        conn = _db()
        try:
            conn.execute(
                "INSERT INTO orders (ts, session_id, order_id, event, status, amount_cents, verified, payload) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (ts, sid, order_id, event, "paid", pay.get("amount"), int(verified),
                 json.dumps(ev, ensure_ascii=False)[:4000]))
            if sid:
                row = conn.execute(
                    "SELECT id FROM pedidos WHERE session_id=? ORDER BY id DESC LIMIT 1",
                    (sid,)).fetchone()
                if row:
                    pedido_id = row[0]
                    conn.execute(
                        "UPDATE pedidos SET status='paid', paid_ts=? WHERE id=?",
                        (ts, pedido_id))
            conn.commit()
        finally:
            conn.close()
        STATS["webhook_paid"] += 1
        log.info("webhook PAGO(verified=%s): %s session=%s order=%s amount=%s pedido=%s",
                 verified, event, sid, order_id, pay.get("amount"), pedido_id)
        if pedido_id:
            asyncio.create_task(_enrich_then_bling(pedido_id, sid))
    return {"received": True}


async def _enrich_then_bling(pid: int, sid: str) -> None:
    await _enrich_from_paggins(pid, sid)
    await _bling_dispatch(pid)


async def _enrich_from_paggins(pid: int, sid: str) -> None:
    """Completa CPF/telefone/endereço do pedido com o que a Paggins devolver na
    sessão pós-pagamento. Necessário desde o passo-1 enxuto (07/07): o site só
    coleta contato+CEP; o comprador digita CPF e endereço na página da Paggins.
    Loga o JSON cru da sessão (prova de campo: o que a Paggins realmente expõe)."""
    p = _pedido_get(pid)
    if not p or not sid:
        return
    missing = [k for k in ("document", "street", "number", "city", "state")
               if not str(p.get(k) or "").strip()]
    if not missing:
        return
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(
                f"{PAGGINS_API_URL}/v1/sdk/checkout-sessions/{sid}?countryCode=BR",
                headers={"Authorization": f"Bearer {PAGGINS_API_KEY}"})
    except httpx.HTTPError as e:
        log.warning("enrich pedido %s: paggins indisponivel (%s)", pid, str(e)[:80])
        return
    if r.status_code != 200:
        log.warning("enrich pedido %s: GET session %s -> %s", pid, sid, r.status_code)
        return
    s = r.json()
    log.info("enrich RAW session %s: %s", sid, json.dumps(s, ensure_ascii=False)[:1800])
    cust = s.get("customer") or {}
    addr = (s.get("shippingAddress") or cust.get("shippingAddress")
            or (s.get("shippingInfo") or {}).get("address") or {})
    updates: dict[str, str] = {}

    def put(col: str, *vals: Any, digits: bool = False, maxlen: int = 120) -> None:
        if str(p.get(col) or "").strip():
            return
        for v in vals:
            v = str(v or "").strip()
            if digits:
                v = re.sub(r"\D", "", v)
            if v:
                updates[col] = v[:maxlen]
                return

    put("document", cust.get("document"), cust.get("cpf"), digits=True, maxlen=14)
    put("phone", cust.get("phone"), cust.get("phoneNumber"), digits=True, maxlen=13)
    put("cep", addr.get("zipCode"), addr.get("cep"), digits=True, maxlen=8)
    put("street", addr.get("street"), addr.get("address"))
    put("number", addr.get("number"), maxlen=12)
    put("complement", addr.get("complement"), maxlen=100)
    put("neighborhood", addr.get("neighborhood"), maxlen=80)
    put("city", addr.get("city"), maxlen=80)
    put("state", addr.get("state"), addr.get("uf"), maxlen=2)
    if updates:
        _pedido_set(pid, **updates)
        log.info("enrich: pedido %s completado da Paggins: %s", pid, sorted(updates))
    else:
        log.warning("enrich: sessao %s sem dados novos (faltando %s)", sid, missing)


# ═══════════════════ Bling (pedido de venda pós-pagamento) ═══════════════════

def _pedido_get(pid: int) -> dict[str, Any] | None:
    conn = _db()
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM pedidos WHERE id=?", (pid,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def _pedido_set(pid: int, **cols: Any) -> None:
    conn = _db()
    try:
        sets = ", ".join(f"{k}=?" for k in cols)
        conn.execute(f"UPDATE pedidos SET {sets} WHERE id=?", (*cols.values(), pid))
        conn.commit()
    finally:
        conn.close()


async def _bling_dispatch(pid: int) -> None:
    """Cria contato+pedido de venda no Bling p/ um pedido pago. Falha → bling_status
    'error'/'pending' (re-tenta pelo painel POST /pedidos/{id}/bling)."""
    p = _pedido_get(pid)
    if not p or p.get("bling_status") == "created":
        return
    faltam = [k for k in ("document", "street", "number", "city", "state")
              if not str(p.get(k) or "").strip()]
    if faltam:
        _pedido_set(pid, bling_status="pending",
                    bling_error="dados p/ NF-e incompletos: " + ", ".join(faltam)
                    + " (Paggins não devolveu — completar via POST /pedidos/{id}/bling"
                    " com os campos no body; dado está no painel Paggins)")
        log.warning("bling pedido %s aguardando dados: %s", pid, faltam)
        return
    if not BLING.configured:
        _pedido_set(pid, bling_status="pending",
                    bling_error="BLING_* env ausente (rodar bling_oauth_bootstrap)")
        log.warning("bling nao configurado; pedido %s fica pending", pid)
        return
    try:
        contato_id = await BLING.ensure_contato(p)
        bling_id = await BLING.create_pedido(contato_id, {
            "order_id": p["order_id"],
            "customer_name": p["name"],
            "itens": json.loads(p["items"] or "[]"),
            "frete_cents": p["frete_cents"] or 0,
            "frete_service": p["frete_service"] or "",
            "coupon": p["coupon"] or "",
            "address": {k: p[k] for k in
                        ("cep", "street", "number", "complement",
                         "neighborhood", "city", "state")},
        })
        _pedido_set(pid, bling_status="created", bling_order_id=str(bling_id),
                    bling_error="")
        log.info("bling OK: pedido %s -> bling #%s", p["order_id"], bling_id)
    except Exception as e:  # noqa: BLE001 — nunca derrubar o webhook
        _pedido_set(pid, bling_status="error", bling_error=str(e)[:400])
        log.error("bling FALHOU pedido %s: %s", p["order_id"], str(e)[:200])


@app.post("/pedidos/{pid}/bling")
async def bling_retry(pid: int, request: Request):
    """Retry do Bling. Body JSON opcional completa dados do pedido antes de
    disparar (p/ pedidos 'pending' do passo-1 enxuto): document, phone, cep,
    street, number, complement, neighborhood, city, state, name, email."""
    denied = _leads_auth(request)
    if denied:
        return denied
    if not _pedido_get(pid):
        raise HTTPException(404, "pedido nao encontrado")
    try:
        body = await request.json()
    except Exception:
        body = {}
    if isinstance(body, dict) and body:
        allowed = {"document", "phone", "cep", "street", "number", "complement",
                   "neighborhood", "city", "state", "name", "email"}
        updates = {}
        for k in allowed & set(body):
            v = str(body[k] or "").strip()
            if k in ("document", "phone", "cep"):
                v = re.sub(r"\D", "", v)
            if k == "document" and v and not _valid_cpf(v):
                raise HTTPException(400, "CPF invalido")
            if v:
                updates[k] = v[:120]
        if updates:
            _pedido_set(pid, **updates)
    await _bling_dispatch(pid)
    p = _pedido_get(pid)
    return {"id": pid, "bling_status": p["bling_status"],
            "bling_order_id": p["bling_order_id"], "bling_error": p["bling_error"]}


# ═══════════════════ STRIPE (checkout 100% nosso — Payment Element) ═══════════
# A página /checkout é NOSSA (checkout-stripe.js no site): coleta contato + CPF +
# endereço + frete + cupom e monta o Payment Element. Este bloco só cria o
# PaymentIntent (total SEMPRE server-side) e confirma via webhook. Roda em
# paralelo ao Paggins — nenhuma rota antiga muda. Sem SDK: REST form-encoded
# via httpx (padrão do serviço). docs.stripe.com/api/payment_intents

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
STRIPE_API = "https://api.stripe.com/v1"
STATS.update({"stripe_received": 0, "stripe_created": 0, "stripe_error": 0,
              "stripe_webhook_received": 0, "stripe_webhook_paid": 0,
              "stripe_webhook_bad_sig": 0})


def _stripe_flat(d: dict, prefix: str = "") -> dict[str, str]:
    """Achata dict aninhado pra bracket notation form-encoded da Stripe:
    {"shipping":{"address":{"city":"SP"}}} -> {"shipping[address][city]":"SP"}."""
    out: dict[str, str] = {}
    for k, v in d.items():
        key = f"{prefix}[{k}]" if prefix else str(k)
        if isinstance(v, dict):
            out.update(_stripe_flat(v, key))
        elif isinstance(v, (list, tuple)):
            for i, item in enumerate(v):
                if isinstance(item, dict):
                    out.update(_stripe_flat(item, f"{key}[{i}]"))
                else:
                    out[f"{key}[{i}]"] = str(item)
        elif isinstance(v, bool):
            out[key] = "true" if v else "false"
        elif v is not None:
            out[key] = str(v)
    return out


async def _stripe_call(method: str, path: str, data: dict | None = None,
                       idem_key: str | None = None) -> dict:
    if not STRIPE_SECRET_KEY:
        raise HTTPException(503, "stripe nao configurado (STRIPE_SECRET_KEY ausente)")
    headers = {}
    if idem_key:
        headers["Idempotency-Key"] = idem_key
    try:
        async with httpx.AsyncClient(timeout=30, auth=(STRIPE_SECRET_KEY, "")) as c:
            r = await c.request(method, f"{STRIPE_API}{path}", headers=headers,
                                data=_stripe_flat(data) if data else None)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"stripe indisponivel: {str(e)[:80]}")
    body = {}
    try:
        body = r.json()
    except Exception:
        pass
    if r.status_code >= 400:
        msg = (body.get("error") or {}).get("message", "")[:200]
        log.error("stripe %s %s -> %s: %s", method, path, r.status_code, msg or r.text[:200])
        STATS["stripe_error"] += 1
        # 402 = pagamento recusado etc; 4xx de request nosso vira 502 genérico
        raise HTTPException(502, "checkout indisponivel")
    return body


async def _stripe_prepare(payload: dict, require_customer: bool = True) -> dict:
    """Validação + preparação comum às rotas Stripe.
    require_customer=True (embedded/2 etapas): customer+address COMPLETOS
    obrigatórios (CPF incluso) e frete Mandaê real por CEP.
    require_customer=False (hosted 1 ETAPA): a Stripe coleta endereço/telefone/
    CPF — frete sem CEP prévio usa a régua do fluxo Paggins simples (>=12 latas
    grátis; kit 6 avulso FLAT_SHIPPING_CENTS)."""
    try:
        lines = _cart_lines(payload.get("items"))
        customer, address = _parse_customer_address(payload)
    except HTTPException:
        STATS["bad_request"] += 1
        raise
    if require_customer:
        if not (customer and address):
            raise HTTPException(400, "customer e address obrigatorios")
        if not customer["document"]:
            raise HTTPException(400, "CPF obrigatorio")
        if not (address["street"] and address["number"] and address["city"]
                and len(address["state"]) == 2):
            raise HTTPException(400, "endereco completo obrigatorio (rua/numero/cidade/UF)")
        if not customer["phone"]:
            raise HTTPException(400, "whatsapp obrigatorio (DDD + numero)")

    subtotal = sum(ln["cents"] * ln["qty"] for ln in lines)
    cans = sum(ln["cans"] for ln in lines)

    coupon_code, discount_pct = _coupon_discount(payload.get("coupon"))
    for ln in lines:
        ln["disc_cents"] = (max(1, (ln["cents"] * (100 - discount_pct) + 50) // 100)
                            if discount_pct else ln["cents"])
    disc_subtotal = sum(ln["disc_cents"] * ln["qty"] for ln in lines)

    frete_cents, frete_service, frete_name, frete_days = 0, "gratis", "Frete Grátis", 0
    if cans < FREE_SHIPPING_CANS:
        if customer and address:
            options = await _mandae_rates(address["cep"], cans, subtotal)
            wanted = str((payload.get("shipping") or {}).get("service") or "economico")
            opt = next((o for o in options if o["service"] == wanted), options[0])
            frete_cents, frete_service = opt["cents"], opt["service"]
            frete_name, frete_days = opt["name"], opt["days"]
        elif FLAT_SHIPPING_CENTS > 0:
            # 1 etapa sem CEP: FLAT (mesma regra do fluxo Paggins drawer)
            frete_cents, frete_service = FLAT_SHIPPING_CENTS, "flat"
            frete_name, frete_days = "Frete (Brasil)", 7

    total = disc_subtotal + frete_cents
    if total < 100:  # guarda-corpo: mínimo da Stripe (~R$0,50) com folga
        raise HTTPException(400, "total abaixo do minimo")

    metadata = _build_metadata(payload.get("meta"))
    metadata["gw"] = "stripe"
    if discount_pct:
        metadata["coupon"] = coupon_code
        metadata["discount_pct"] = str(discount_pct)
    return {
        "lines": lines, "customer": customer, "address": address,
        "subtotal": subtotal, "total": total, "cans": cans,
        "coupon_code": coupon_code, "discount_pct": discount_pct,
        "frete_cents": frete_cents, "frete_service": frete_service,
        "frete_name": frete_name, "frete_days": frete_days,
        "metadata": metadata,
        "order_id": f"hyu-{uuid.uuid4().hex[:12]}",
        "items_txt": " + ".join((f"{ln['qty']}x " if ln["qty"] > 1 else "")
                                + ln["name"] for ln in lines),
    }


def _stripe_save_pedido(o: dict, session_ref: str) -> None:
    """Grava o pedido casável pelo webhook via session_ref (pi_... no embedded,
    cs_... no hosted). No 1 etapa customer/address vêm None — o webhook completa
    com o que a Stripe coletou (_stripe_fill_from_session)."""
    cust = o.get("customer") or {"name": "", "document": "", "email": "", "phone": ""}
    addr = o.get("address") or {"cep": "", "street": "", "number": "",
                                "complement": "", "neighborhood": "",
                                "city": "", "state": ""}
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO pedidos (ts, order_id, session_id, status, "
            "name, document, email, phone, cep, street, number, "
            "complement, neighborhood, city, state, items, "
            "subtotal_cents, frete_cents, frete_service, total_cents, "
            "coupon, meta, bling_status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"),
             o["order_id"], session_ref, "created",
             cust["name"], cust["document"], cust["email"], cust["phone"],
             addr["cep"], addr["street"], addr["number"],
             addr["complement"], addr["neighborhood"],
             addr["city"], addr["state"],
             json.dumps([{k: ln[k] for k in ("sku", "name", "qty", "cents", "cans")}
                         for ln in o["lines"]], ensure_ascii=False),
             o["subtotal"], o["frete_cents"], o["frete_service"], o["total"],
             o["coupon_code"], json.dumps(o["metadata"], ensure_ascii=False), ""))
        conn.commit()
    finally:
        conn.close()


@app.post("/stripe/checkout")
async def stripe_checkout(request: Request):
    """Checkout EMBEDDED (Payment Element na nossa página) — cria PaymentIntent."""
    STATS["stripe_received"] += 1
    try:
        payload = await request.json()
    except Exception:
        STATS["bad_request"] += 1
        raise HTTPException(400, "JSON invalido")
    o = await _stripe_prepare(payload)
    lines, customer, address = o["lines"], o["customer"], o["address"]
    order_id, metadata, items_txt = o["order_id"], o["metadata"], o["items_txt"]
    total, frete_cents, frete_service = o["total"], o["frete_cents"], o["frete_service"]
    subtotal, coupon_code, discount_pct = o["subtotal"], o["coupon_code"], o["discount_pct"]
    pi_meta = {"order_id": order_id, "cpf": customer["document"],
               "items": items_txt[:480], **metadata}
    pi = await _stripe_call("POST", "/payment_intents", {
        "amount": total,
        "currency": "brl",
        "automatic_payment_methods": {"enabled": True},
        "description": f"HYU {order_id} — {items_txt}"[:900],
        "receipt_email": customer["email"],
        "metadata": pi_meta,
        "shipping": {
            "name": customer["name"],
            "phone": f"+55{customer['phone']}",
            "address": {
                "line1": f"{address['street']}, {address['number']}",
                "line2": (f"{address['complement']} — " if address["complement"]
                          else "") + address["neighborhood"],
                "city": address["city"], "state": address["state"],
                "postal_code": address["cep"], "country": "BR",
            },
        },
    }, idem_key=order_id)

    pi_id = str(pi.get("id") or "")
    client_secret = str(pi.get("client_secret") or "")
    if not (pi_id and client_secret):
        STATS["stripe_error"] += 1
        raise HTTPException(502, "checkout indisponivel")
    _stripe_save_pedido(o, pi_id)
    STATS["stripe_created"] += 1
    log.info("stripe checkout %s -> %s total=%s frete=%s/%s coupon=%s", order_id,
             pi_id, total, frete_service or "-", frete_cents, coupon_code or "-")
    return {"clientSecret": client_secret, "publishableKey": STRIPE_PUBLISHABLE_KEY,
            "orderId": order_id, "totalCents": total, "subtotalCents": subtotal,
            "freteCents": frete_cents, "freteService": frete_service,
            "coupon": coupon_code, "discountPct": discount_pct}


@app.post("/stripe/hosted")
async def stripe_hosted(request: Request):
    """Checkout HOSPEDADO da Stripe (checkout.stripe.com — confiança da marca):
    cria uma Checkout Session com os itens do carrinho (price_data inline,
    preço já com cupom), frete como shipping_option (linha própria "Frete"),
    e-mail pré-preenchido e NOSSO endereço no payment_intent (o cliente NÃO
    redigita nada) -> devolve a URL pro redirect."""
    STATS["stripe_received"] += 1
    try:
        payload = await request.json()
    except Exception:
        STATS["bad_request"] += 1
        raise HTTPException(400, "JSON invalido")
    # 1 ETAPA (default do site): payload SEM customer/address — a Stripe coleta
    # endereço+telefone+CPF. Com customer completo = fluxo 2 etapas (página nossa).
    one_step = not (isinstance(payload.get("customer"), dict)
                    and isinstance(payload.get("address"), dict)
                    and (payload.get("address") or {}).get("cep"))
    o = await _stripe_prepare(payload, require_customer=not one_step)
    customer, address = o["customer"], o["address"]
    order_id, metadata = o["order_id"], o["metadata"]

    origin = str(payload.get("origin") or "").rstrip("/")
    base = origin if origin in HYU_ORIGINS else SITE_BASE

    tag = (f" · {o['discount_pct']}% OFF cupom {o['coupon_code']}"
           if o["discount_pct"] else "")
    line_items = []
    for ln in o["lines"]:
        item = {
            "quantity": ln["qty"],
            "price_data": {
                "currency": "brl",
                "unit_amount": ln["disc_cents"],
                "product_data": {
                    "name": (ln["name"][:250 - len(tag)] + tag) if tag else ln["name"][:250],
                    "images": [f"{SITE_BASE}/img/kits/{ln['img']}.webp"],
                },
            },
        }
        if ln.get("desc"):
            item["price_data"]["product_data"]["description"] = ln["desc"][:300]
        line_items.append(item)

    est = ({"delivery_estimate": {
              "minimum": {"unit": "business_day", "value": max(1, o["frete_days"])},
              "maximum": {"unit": "business_day", "value": max(1, o["frete_days"]) + 3}}}
           if o["frete_days"] else {})
    body = {
        "mode": "payment",
        "locale": "pt-BR",
        "line_items": line_items,
        "client_reference_id": order_id,
        "metadata": {**metadata, "order_id": order_id},
        "payment_intent_data": {
            "description": f"HYU {order_id} — {o['items_txt']}"[:900],
            "metadata": {"order_id": order_id, "gw": "stripe"},
        },
        "shipping_options": [{
            "shipping_rate_data": {
                "type": "fixed_amount",
                "display_name": (o["frete_name"] if o["frete_cents"]
                                 else "Frete Grátis")[:50],
                "fixed_amount": {"amount": o["frete_cents"], "currency": "brl"},
                **est,
            },
        }],
        "success_url": f"{base}/obrigado/?gw=stripe&ref={order_id}"
                       "&session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": f"{base}/?checkout=cancelado",
    }
    if one_step:
        # Stripe coleta TUDO: endereço de entrega BR, telefone e CPF (custom field
        # — tax_id_collection não mostra campo pra BR). Webhook lê de volta pra NF-e.
        body["shipping_address_collection"] = {"allowed_countries": ["BR"]}
        body["phone_number_collection"] = {"enabled": True}
        body["custom_fields"] = [{
            "key": "cpf",
            "label": {"type": "custom", "custom": "CPF (pra emitir sua nota fiscal)"},
            "type": "numeric",
            "numeric": {"minimum_length": 11, "maximum_length": 11},
        }]
    else:
        body["customer_email"] = customer["email"]
        body["metadata"]["cpf"] = customer["document"]
        body["payment_intent_data"]["shipping"] = {
            "name": customer["name"],
            "phone": f"+55{customer['phone']}",
            "address": {
                "line1": f"{address['street']}, {address['number']}",
                "line2": (f"{address['complement']} — " if address["complement"]
                          else "") + address["neighborhood"],
                "city": address["city"], "state": address["state"],
                "postal_code": address["cep"], "country": "BR",
            },
        }
    sess = await _stripe_call("POST", "/checkout/sessions", body, idem_key=order_id)
    cs_id, url = str(sess.get("id") or ""), str(sess.get("url") or "")
    if not (cs_id and url):
        STATS["stripe_error"] += 1
        raise HTTPException(502, "checkout indisponivel")
    _stripe_save_pedido(o, cs_id)
    STATS["stripe_created"] += 1
    log.info("stripe hosted %s -> %s total=%s frete=%s/%s coupon=%s", order_id,
             cs_id, o["total"], o["frete_service"] or "-", o["frete_cents"],
             o["coupon_code"] or "-")
    return {"url": url, "orderId": order_id, "sessionId": cs_id,
            "totalCents": o["total"], "freteCents": o["frete_cents"],
            "freteService": o["frete_service"], "coupon": o["coupon_code"],
            "discountPct": o["discount_pct"]}


def _stripe_fill_from_session(pid: int, obj: dict) -> None:
    """1 ETAPA: completa o pedido com o que a Stripe coletou na Checkout Session
    (customer_details, shipping, custom_fields[cpf]) — só campos vazios.
    line1 vem "Rua X, 123" → melhor esforço pra separar rua/número (Bling exige)."""
    p = _pedido_get(pid)
    if not p:
        return
    cd = obj.get("customer_details") or {}
    ship = ((obj.get("collected_information") or {}).get("shipping_details")
            or obj.get("shipping_details") or {})
    addr = ship.get("address") or cd.get("address") or {}
    cpf = ""
    for cf in obj.get("custom_fields") or []:
        if cf.get("key") == "cpf":
            v = (cf.get("numeric") or {}).get("value") or (cf.get("text") or {}).get("value")
            cpf = re.sub(r"\D", "", str(v or ""))
    line1 = str(addr.get("line1") or "").strip()
    line2 = str(addr.get("line2") or "").strip()
    m = re.match(r"^(.*?)[,\s]+(\d+\s*[A-Za-z0-9/\-]*)$", line1)
    street, number = (m.group(1).strip(" ,"), m.group(2).strip()) if m else (line1, "")
    if not number and line2:
        m2 = re.match(r"^[Nn]?[ºo°.]?\s*(\d+\S*)\s*[,\-]?\s*(.*)$", line2)
        if m2:
            number, line2 = m2.group(1), m2.group(2).strip()
    phone = re.sub(r"\D", "", str(cd.get("phone") or ""))
    if phone.startswith("55") and len(phone) > 11:
        phone = phone[2:]
    vals = {
        "name": str(ship.get("name") or cd.get("name") or "").strip()[:120],
        "email": str(cd.get("email") or "").strip()[:160].lower(),
        "phone": phone[:13],
        "document": cpf[:14] if (not cpf or _valid_cpf(cpf)) else "",
        "cep": re.sub(r"\D", "", str(addr.get("postal_code") or ""))[:8],
        "street": street[:120],
        "number": (number or ("S/N" if street else ""))[:12],
        "complement": line2[:100],
        "city": str(addr.get("city") or "").strip()[:80],
        "state": str(addr.get("state") or "").strip()[:2].upper(),
    }
    updates = {k: v for k, v in vals.items() if v and not str(p.get(k) or "").strip()}
    if updates:
        _pedido_set(pid, **updates)
        log.info("stripe fill: pedido %s completado da sessao: %s", pid, sorted(updates))


def _stripe_webhook_verified(raw: bytes, header: str) -> bool:
    """Stripe-Signature: 't=<ts>,v1=<hmac>,...' — HMAC-SHA256 do '<ts>.<raw>' com
    o STRIPE_WEBHOOK_SECRET (whsec_... usado como chave, INTEIRO). Tolerância 10min."""
    if not (STRIPE_WEBHOOK_SECRET and header):
        return False
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    ts, v1s = parts.get("t", ""), [v for k, v in
                                   (p.split("=", 1) for p in header.split(",") if "=" in p)
                                   if k == "v1"]
    if not (ts.isdigit() and v1s):
        return False
    if abs(time.time() - int(ts)) > 600:
        return False
    expected = hmac.new(STRIPE_WEBHOOK_SECRET.encode(),
                        f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, v) for v in v1s)


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    """payment_intent.succeeded -> pedido pago -> Bling. Assinatura ESTRITA
    (diferente do Paggins: o esquema da Stripe é documentado e estável) —
    mismatch = 400 e a Stripe re-tenta."""
    raw = await request.body()
    STATS["stripe_webhook_received"] += 1
    if not _stripe_webhook_verified(raw, request.headers.get("stripe-signature", "")):
        STATS["stripe_webhook_bad_sig"] += 1
        raise HTTPException(400, "assinatura invalida")
    try:
        ev = json.loads(raw or b"{}")
    except Exception:
        raise HTTPException(400, "JSON invalido")
    event = str(ev.get("type") or "")
    obj = (ev.get("data") or {}).get("object") or {}
    obj_id = str(obj.get("id") or "")
    # embedded (pi_...) OU hosted (cs_...); no hosted o completed de cartão já
    # vem payment_status=paid — PIX (futuro) vem unpaid e paga no async_...
    paid = (event == "payment_intent.succeeded"
            or (event == "checkout.session.completed"
                and obj.get("payment_status") == "paid")
            or event == "checkout.session.async_payment_succeeded")
    if paid and obj_id:
        amount = obj.get("amount_received") or obj.get("amount_total") or obj.get("amount")
        order_id = str((obj.get("metadata") or {}).get("order_id")
                       or obj.get("client_reference_id") or "")
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        pedido_id = None
        conn = _db()
        try:
            conn.execute(
                "INSERT INTO orders (ts, session_id, order_id, event, status, "
                "amount_cents, verified, payload) VALUES (?,?,?,?,?,?,?,?)",
                (ts, obj_id, order_id, event, "paid", amount, 1,
                 json.dumps(ev, ensure_ascii=False)[:4000]))
            row = conn.execute(
                "SELECT id, status FROM pedidos WHERE session_id=? OR order_id=? "
                "ORDER BY id DESC LIMIT 1", (obj_id, order_id)).fetchone()
            if row and row[1] != "paid":  # idempotente: cs+pi do mesmo pedido
                pedido_id = row[0]
                conn.execute("UPDATE pedidos SET status='paid', paid_ts=? WHERE id=?",
                             (ts, pedido_id))
            conn.commit()
        finally:
            conn.close()
        STATS["stripe_webhook_paid"] += 1
        log.info("stripe webhook PAGO: %s id=%s order=%s amount=%s pedido=%s",
                 event, obj_id, order_id, amount, pedido_id)
        if pedido_id:
            # 1 etapa: completa o pedido com o que a Stripe coletou (endereço/
            # telefone/CPF) antes do Bling; 2 etapas já veio completo (no-op)
            if event.startswith("checkout.session."):
                _stripe_fill_from_session(pedido_id, obj)
            asyncio.create_task(_bling_dispatch(pedido_id))
    elif event in ("payment_intent.payment_failed",
                   "checkout.session.async_payment_failed"):
        log.warning("stripe webhook FALHA %s id=%s: %s", event, obj_id,
                    ((obj.get("last_payment_error") or {}).get("message") or "")[:200])
    return {"received": True}


@app.get("/stripe/session/{pi_id}")
async def stripe_session(pi_id: str):
    """Status do PaymentIntent (pro /obrigado). PIX é assíncrono: 'processing'
    até o webhook confirmar — a página mostra 'aguardando confirmação'."""
    if not re.match(r"^pi_[A-Za-z0-9]+$", pi_id):
        raise HTTPException(400, "payment_intent invalido")
    pi = await _stripe_call("GET", f"/payment_intents/{pi_id}")
    status = str(pi.get("status") or "")
    return {"id": pi.get("id"), "status": status,
            "paymentStatus": "paid" if status == "succeeded" else status,
            "totalAmount": pi.get("amount"), "currency": pi.get("currency")}


@app.get("/stripe/csession/{cs_id}")
async def stripe_csession(cs_id: str):
    """Status da Checkout Session HOSPEDADA (pro /obrigado do fluxo hosted)."""
    if not re.match(r"^cs_[A-Za-z0-9_]+$", cs_id):
        raise HTTPException(400, "session invalida")
    s = await _stripe_call("GET", f"/checkout/sessions/{cs_id}")
    pay = str(s.get("payment_status") or "")
    return {"id": s.get("id"), "status": s.get("status"),
            "paymentStatus": "paid" if pay == "paid" else pay,
            "totalAmount": s.get("amount_total"), "currency": s.get("currency")}


# ═══════════════════ SHOPIFY (checkout hospedado via Draft Order) ═══════════
# Fluxo alternativo (gate ?gw=shopify no site de teste): o bridge cria um DRAFT
# ORDER com os itens do carrinho e devolve a invoice_url = checkout hospedado da
# Shopify (alta conversão; ela coleta endereço/frete/pagamento). Combos viram
# variantes reais (imagem no checkout); flavor×tier e MIX viram custom line items
# (preço do catálogo + composição). Inerte sem SHOPIFY_ADMIN_TOKEN (503).
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "").strip()
SHOPIFY_ADMIN_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN", "").strip()
SHOPIFY_API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2026-07")
try:
    SHOPIFY_VARIANTS = {str(k): int(v) for k, v in json.loads(
        os.environ.get("SHOPIFY_VARIANTS_JSON", "{}")).items()}
except Exception:
    SHOPIFY_VARIANTS = {}
SHOPIFY_VARIANTS = SHOPIFY_VARIANTS or {   # SKU do combo -> variant_id na loja (imagem)
    "KITENERGY": 43669515239514, "KITSODA": 43669515272282,
    "SUPERKIT": 43669515305050, "KIT24": 43669515370586,
}
SHOPIFY_API_SECRET = os.environ.get("SHOPIFY_API_SECRET", "").strip()  # HMAC do webhook


def _variant_id_for_line(ln: dict[str, Any]) -> int | None:
    """SKU normalizado da linha -> variant_id da Shopify (mix colapsa no MIXK6/MIXK12)."""
    sku = ln["sku"].replace("HYU-", "")
    if sku.startswith("MIXK6"):
        return SHOPIFY_VARIANTS.get("MIXK6")
    if sku.startswith("MIXK12"):
        return SHOPIFY_VARIANTS.get("MIXK12")
    return SHOPIFY_VARIANTS.get(sku)


def _cans_from_variant_sku(sku: str) -> int:
    """Nº de latas a partir do SKU da VARIANTE Shopify (usado no Carrier Service)."""
    s = (sku or "").upper()
    for c in COMBOS.values():
        if c["sku"] == s:
            return c["cans"]
    if "K12" in s:   # MIXK12 / *-K12
        return 12
    if "K6" in s:    # MIXK6 / *-K6
        return 6
    return 0


def _split_street_number(line1: str, line2: str = "") -> tuple[str, str, str]:
    """"Rua X, 123" -> (rua, numero, complemento). Bling exige numero separado."""
    line1, line2 = (line1 or "").strip(), (line2 or "").strip()
    m = re.match(r"^(.*?)[,\s]+(\d+\s*[A-Za-z0-9/\-]*)$", line1)
    street, number = (m.group(1).strip(" ,"), m.group(2).strip()) if m else (line1, "")
    if not number and line2:
        m2 = re.match(r"^[Nn]?[ºo°.]?\s*(\d+\S*)\s*[,\-]?\s*(.*)$", line2)
        if m2:
            number, line2 = m2.group(1), m2.group(2).strip()
    return street, (number or ("S/N" if street else "")), line2


def _shopify_webhook_verified(raw: bytes, hmac_header: str) -> bool:
    if not (SHOPIFY_API_SECRET and hmac_header):
        return False
    digest = base64.b64encode(
        hmac.new(SHOPIFY_API_SECRET.encode(), raw, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(digest, hmac_header)


def _reais(cents: int) -> str:
    return f"{cents / 100:.2f}"


async def _shopify_call(method: str, path: str, data: dict | None = None) -> dict:
    if not (SHOPIFY_STORE and SHOPIFY_ADMIN_TOKEN):
        raise HTTPException(503, "shopify nao configurado (SHOPIFY_ADMIN_TOKEN ausente)")
    url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}{path}"
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.request(method, url, json=data, headers={
                "X-Shopify-Access-Token": SHOPIFY_ADMIN_TOKEN,
                "Content-Type": "application/json", "Accept": "application/json"})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"shopify indisponivel: {str(e)[:80]}")
    if r.status_code >= 400:
        log.error("shopify %s %s -> %s: %s", method, path, r.status_code, r.text[:200])
        raise HTTPException(502, f"shopify {r.status_code}")
    return r.json()


async def _shopify_localized_cpf(order_gid_num: str) -> str:
    """CPF do campo NATIVO da Shopify BR (localizedFields TAX_CREDENTIAL_BR, coletado em
    'Informações adicionais' do checkout). Só GraphQL — não vem no payload do webhook.
    Fallback pra quando o gateway não injetar customer_document nos note_attributes."""
    q = ("{ order(id: \"gid://shopify/Order/%s\") { localizedFields(first: 5) "
         "{ nodes { key value } } } }" % order_gid_num)
    try:
        d = await _shopify_call("POST", "/graphql.json", {"query": q})
        nodes = (((d.get("data") or {}).get("order") or {})
                 .get("localizedFields") or {}).get("nodes") or []
        for n in nodes:
            if n.get("key") == "TAX_CREDENTIAL_BR":
                return re.sub(r"\D", "", str(n.get("value") or ""))
    except Exception as e:
        log.error("localizedFields CPF falhou order=%s: %s", order_gid_num, str(e)[:120])
    return ""


@app.post("/shopify/checkout")
async def shopify_checkout(request: Request):
    """Carrinho -> draft order -> invoice_url (checkout hospedado da Shopify)."""
    payload = await request.json()
    lines = _cart_lines(payload.get("items"))
    code, pct = _coupon_discount(payload.get("coupon"))
    li: list[dict[str, Any]] = []
    for ln in lines:
        sku = ln["sku"].replace("HYU-", "")   # ex: SUPERKIT, MACAVERDE-K6, MIXK12-MV4TP4
        if sku.startswith("MIXK6"):
            vid = SHOPIFY_VARIANTS.get("MIXK6")
        elif sku.startswith("MIXK12"):
            vid = SHOPIFY_VARIANTS.get("MIXK12")
        else:
            vid = SHOPIFY_VARIANTS.get(sku)
        if vid:  # produto real -> imagem no checkout
            item: dict[str, Any] = {"variant_id": vid, "quantity": ln["qty"]}
            if "MIX" in sku:  # composição de sabores do mix
                comp = ln["name"].split("—", 1)[1].strip() if "—" in ln["name"] else ln["name"]
                item["properties"] = [{"name": "Sabores", "value": comp[:255]}]
            li.append(item)
        else:  # fallback custom (sem imagem) p/ item sem produto cadastrado
            item = {"title": ln["name"], "price": _reais(ln["cents"]), "quantity": ln["qty"]}
            if ln.get("desc"):
                item["properties"] = [{"name": "Info", "value": ln["desc"][:200]}]
            li.append(item)
    draft: dict[str, Any] = {"line_items": li, "tags": "site-hyu",
                             "note": "Pedido do site HYU (checkout Shopify)."}
    meta = _build_metadata(payload.get("meta"))
    if meta:
        draft["note_attributes"] = [{"name": k, "value": v} for k, v in meta.items()]
    if pct > 0:
        draft["applied_discount"] = {"title": code, "description": f"Cupom {code}",
                                     "value_type": "percentage", "value": str(pct)}
    resp = await _shopify_call("POST", "/draft_orders.json", {"draft_order": draft})
    do = resp.get("draft_order", {})
    url = do.get("invoice_url")
    if not url:
        raise HTTPException(502, "shopify sem invoice_url")
    log.info("shopify draft %s total=%s", do.get("id"), do.get("total_price"))
    return {"url": url}


@app.post("/shopify/cart")
async def shopify_cart(request: Request):
    """Carrinho -> Storefront Cart -> checkoutUrl (checkout PADRÃO da Shopify, onde o
    Carrier Service coteia o frete Mandaê em tempo real — ao contrário do draft order).
    Substitui o /shopify/checkout no site de teste. Composição do mix vai em line item
    properties; CPF/utm vão em cart attributes (viram note_attributes na order -> Bling)."""
    if not shopify_store.configured():
        raise HTTPException(503, "shopify storefront nao configurado (SHOPIFY_STOREFRONT_TOKEN)")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "JSON invalido")
    lines = _cart_lines(payload.get("items"))
    code, _pct = _coupon_discount(payload.get("coupon"))
    sf_lines: list[dict[str, Any]] = []
    for ln in lines:
        vid = _variant_id_for_line(ln)
        if not vid:
            raise HTTPException(502, f"variante Shopify ausente p/ {ln['sku']} "
                                     "(rodar _shopify_seed_all.py + SHOPIFY_VARIANTS_JSON)")
        item: dict[str, Any] = {"merchandiseId": shopify_store.variant_gid(vid),
                                "quantity": ln["qty"]}
        if "MIX" in ln["sku"] and "—" in ln["name"]:
            item["attributes"] = [{"key": "Sabores", "value": ln["name"].split("—", 1)[1].strip()[:255]}]
        sf_lines.append(item)
    attrs = _build_metadata(payload.get("meta"))
    cust = payload.get("customer") or {}
    cpf = re.sub(r"\D", "", str(cust.get("document") or payload.get("cpf") or ""))
    if cpf:
        attrs["cpf"] = cpf
    if code:
        attrs["coupon"] = code
    buyer: dict[str, str] = {}
    if cust.get("email"):
        buyer["email"] = str(cust["email"]).strip()[:160]
    if cust.get("phone"):
        buyer["phone"] = "+55" + re.sub(r"\D", "", str(cust["phone"]))[-11:]
    try:
        url = await shopify_store.create_cart(
            sf_lines, discount_codes=[code] if code else None,
            attributes=attrs, buyer=buyer or None)
    except shopify_store.StorefrontError as e:
        log.error("shopify cart: %s", str(e)[:200])
        raise HTTPException(502, "checkout indisponivel")
    log.info("shopify cart -> %s… (lines=%d coupon=%s)", url[:48], len(sf_lines), code or "-")
    return {"url": url}


@app.post("/shopify/rates")
async def shopify_rates(request: Request):
    """Callback do Carrier Service da Shopify: rate request (destino + itens) ->
    opções Mandaê (grátis >=12 latas). Registrado por _shopify_carrier_register.py.
    Formato de resposta: rates[].{service_name,service_code,total_price(cents str),currency}."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "JSON invalido")
    rate = payload.get("rate") or {}
    cep = re.sub(r"\D", "", str((rate.get("destination") or {}).get("postal_code", "")))
    cans, declared = 0, 0
    for it in rate.get("items") or []:
        qty = int(it.get("quantity") or 1)
        cans += _cans_from_variant_sku(str(it.get("sku") or "")) * qty
        declared += int(it.get("price") or 0) * qty   # price já em cents (Shopify)
    if len(cep) != 8 or cans <= 0:
        return {"rates": []}
    free = cans >= FREE_SHIPPING_CANS
    try:
        options = await _mandae_rates(cep, cans, declared)
    except HTTPException:
        if not free:
            return {"rates": []}   # sem cotação e não-grátis: Shopify usa fallback rate
        options = [{"service": "economico", "name": "Frete Grátis", "days": 7, "cents": 0}]
    rates = []
    for o in options:
        days = o.get("days") or 0
        rates.append({
            "service_name": "Frete Grátis" if free else o["name"],
            "service_code": "MANDAE_" + str(o["service"]).upper(),
            "total_price": str(0 if free else o["cents"]),   # cents
            "currency": "BRL",
            "description": f"Entrega em ~{days} dia(s) úteis" if days else "",
        })
    return {"rates": rates}


# ═══════════════════ AFILIADOS (tag no cart attribute -> comissao) ═══════════════════

HOLD_DAYS = 7   # dias de carencia pos-pagamento antes da comissao virar sacavel


def _norm_tag(s: Any) -> str:
    """Tag do afiliado: A-Z0-9 sem acento, 3-20 chars. Case-insensitive."""
    t = re.sub(r"[^A-Za-z0-9]", "", str(s or "")).upper()
    return t[:20]


def _credit_commission(order_id: str, pedido_id: int, ref: str, base_cents: int,
                       coupon: str = "") -> None:
    """Credita a comissao do afiliado da venda. Duas vias de atribuicao, nessa ordem:
      1. `ref`  — a tag do LINK (?ref=), que veio no cart attribute;
      2. `coupon` — o cupom da order, casado com o campo `cupom` do afiliado
         (cobre quem divulga so o cupom de influencer /ARTHURPC ou digita no checkout).
    Silencioso quando nao ha nenhuma das duas / afiliado desconhecido ou inativo — o
    pedido nunca pode falhar por causa do afiliado. Idempotente por order_id (UNIQUE)."""
    if base_cents <= 0:
        return
    tag = _norm_tag(ref)
    cup = _norm_tag(coupon)
    if not tag and not cup:
        return
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = _db()
    try:
        row = via = None
        if tag:
            row = conn.execute(
                "SELECT tag, pct FROM afiliados WHERE tag=? AND active=1", (tag,)).fetchone()
            via = "link"
        if not row and cup:
            row = conn.execute(
                "SELECT tag, pct FROM afiliados WHERE cupom=? AND active=1", (cup,)).fetchone()
            via = "cupom"
        if not row:
            log.info("comissao IGNORADA order=%s ref=%s cupom=%s (afiliado desconhecido/inativo)",
                     order_id, tag or "-", cup or "-")
            return
        pct = float(row[1] or AFILIADO_PCT)
        valor = int(round(base_cents * pct / 100))
        conn.execute(
            "INSERT OR IGNORE INTO comissoes (ts, tag, pedido_id, order_id, base_cents, "
            "pct, valor_cents, status, via) VALUES (?,?,?,?,?,?,?,'pending',?)",
            (ts, row[0], pedido_id, order_id, base_cents, pct, valor, via))
        conn.commit()
        log.info("comissao CREDITADA order=%s tag=%s via=%s base=%s pct=%s valor=%s",
                 order_id, row[0], via, base_cents, pct, valor)
    except Exception as e:                                  # nunca derruba o webhook
        log.error("comissao falhou order=%s: %s", order_id, str(e)[:200])
    finally:
        conn.close()


@app.post("/shopify/webhook")
async def shopify_webhook(request: Request):
    """orders/paid da Shopify -> cria contato+pedido de venda no Bling (NF-e/etiqueta/
    rastreio, via integração nativa Bling↔Mandaê). HMAC via SHOPIFY_API_SECRET.
    Registrado por _shopify_webhook_register.py. Idempotente por order_id."""
    raw = await request.body()
    STATS["webhook_received"] = STATS.get("webhook_received", 0) + 1
    if not _shopify_webhook_verified(raw, request.headers.get("x-shopify-hmac-sha256", "")):
        STATS["webhook_bad_sig"] = STATS.get("webhook_bad_sig", 0) + 1
        raise HTTPException(401, "assinatura invalida")
    try:
        o = json.loads(raw or b"{}")
    except Exception:
        raise HTTPException(400, "JSON invalido")
    order_id = "shopify-" + str(o.get("id") or o.get("order_number") or "")
    conn = _db()
    try:
        dup = conn.execute("SELECT id FROM pedidos WHERE order_id=? LIMIT 1",
                           (order_id,)).fetchone()
    finally:
        conn.close()
    if dup:
        return {"ok": True, "pedido": dup[0], "dup": True}

    ship = o.get("shipping_address") or o.get("billing_address") or {}
    cust = o.get("customer") or {}
    attrs = {a.get("name"): a.get("value")
             for a in (o.get("note_attributes") or []) if a.get("name")}
    # a Appmax injeta CPF + endereço ESTRUTURADO nos note_attributes — preferir esses
    cpf = re.sub(r"\D", "", str(attrs.get("cpf") or attrs.get("customer_document") or ""))
    if not _valid_cpf(cpf):     # sem CPF do gateway -> campo nativo BR do checkout
        try:                    # nunca pode abortar o webhook (pedido ainda nem foi gravado)
            cpf = await _shopify_localized_cpf(str(o.get("id") or "")) or cpf
        except Exception as e:
            log.error("fallback CPF falhou order=%s: %s", order_id, str(e)[:120])
    name = str(ship.get("name")
               or f"{cust.get('first_name', '')} {cust.get('last_name', '')}").strip()[:120]
    phone = re.sub(r"\D", "", str(ship.get("phone") or o.get("phone")
                                  or attrs.get("shipping_phone") or cust.get("phone") or ""))
    if phone.startswith("55") and len(phone) > 11:
        phone = phone[2:]
    email = str(o.get("email") or cust.get("email") or "").strip()[:160].lower()
    # endereço: Appmax (shipping_* estruturado, JÁ com bairro) > shipping_address do Shopify
    # (o Shopify junta rua+bairro em address1/2 e não tem campo de bairro — Bling exige bairro)
    if attrs.get("shipping_street_name"):
        street = str(attrs.get("shipping_street_name") or "")
        number = str(attrs.get("shipping_street_number") or "S/N")
        complement = str(attrs.get("shipping_street_complement") or "")
        neighborhood = str(attrs.get("shipping_neighborhood") or "")
        city = str(attrs.get("shipping_city") or ship.get("city") or "")
        state = str(attrs.get("shipping_province") or ship.get("province_code") or "")[:2].upper()
        cep = re.sub(r"\D", "", str(attrs.get("shipping_postcode") or ship.get("zip") or ""))
    else:
        street, number, complement = _split_street_number(
            str(ship.get("address1") or ""), str(ship.get("address2") or ""))
        neighborhood = ""
        city = str(ship.get("city") or "")
        state = str(ship.get("province_code") or "")[:2].upper()
        cep = re.sub(r"\D", "", str(ship.get("zip") or ""))
    ship_lines = o.get("shipping_lines") or []
    frete_cents = int(round(float((ship_lines[0].get("price") if ship_lines else 0) or 0) * 100))
    frete_service = ((ship_lines[0].get("title") if ship_lines else "") or "")[:60]
    disc = o.get("discount_codes") or []
    coupon = ((disc[0].get("code") if disc else "") or "")[:40]
    itens = [{"sku": (li.get("sku") or li.get("title") or "")[:60],
              "name": (li.get("title") or "")[:120],
              "qty": int(li.get("quantity") or 1),
              "cents": int(round(float(li.get("price") or 0) * 100))}
             for li in (o.get("line_items") or [])]
    subtotal = sum(i["cents"] * i["qty"] for i in itens)
    total = int(round(float(o.get("total_price") or 0) * 100))
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO pedidos (ts, order_id, session_id, status, paid_ts, "
            "name, document, email, phone, cep, street, number, complement, "
            "neighborhood, city, state, items, subtotal_cents, frete_cents, "
            "frete_service, total_cents, coupon, meta, bling_status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, order_id, order_id, "paid", ts,
             name, cpf if _valid_cpf(cpf) else "", email, phone[:13],
             cep[:8], street[:120], number[:12],
             complement[:100], neighborhood[:80], city.strip()[:80], state,
             json.dumps(itens, ensure_ascii=False), subtotal, frete_cents,
             frete_service, total, coupon,
             json.dumps({"gw": "shopify",
                         **{k: v for k, v in attrs.items() if k != "cpf"}}, ensure_ascii=False),
             ""))
        pid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    STATS["webhook_paid"] = STATS.get("webhook_paid", 0) + 1
    log.info("shopify webhook PAGO order=%s pedido=%s total=%s", order_id, pid, total)
    # comissao de afiliado: base = subtotal de PRODUTOS pos-desconto, sem frete
    base = int(round(float(o.get("current_subtotal_price") or 0) * 100)) or subtotal
    _credit_commission(order_id, pid, attrs.get("ref") or "", base, coupon)
    asyncio.create_task(_bling_dispatch(pid))
    return {"ok": True, "pedido": pid}


@app.post("/shopify/refund")
async def shopify_refund(request: Request):
    """refunds/create da Shopify -> estorna a comissao do afiliado (se ainda nao paga).
    Registrado por _shopify_affiliate_setup.py. Mesmo HMAC do orders/paid."""
    raw = await request.body()
    if not _shopify_webhook_verified(raw, request.headers.get("x-shopify-hmac-sha256", "")):
        raise HTTPException(401, "assinatura invalida")
    try:
        r = json.loads(raw or b"{}")
    except Exception:
        raise HTTPException(400, "JSON invalido")
    order_id = "shopify-" + str(r.get("order_id") or "")
    conn = _db()
    try:
        cur = conn.execute(
            "UPDATE comissoes SET status='reversed' "
            "WHERE order_id=? AND status='pending'", (order_id,))
        conn.commit()
        n = cur.rowcount
    finally:
        conn.close()
    if n:
        log.info("comissao ESTORNADA order=%s", order_id)
    return {"ok": True, "reversed": n}


@app.get("/healthz")
async def healthz():
    return {"ok": True, "has_key": bool(PAGGINS_API_KEY),
            "stripe": bool(STRIPE_SECRET_KEY and STRIPE_PUBLISHABLE_KEY),
            "shopify": bool(SHOPIFY_STORE and SHOPIFY_ADMIN_TOKEN),
            "shopify_storefront": shopify_store.configured(),
            "shopify_webhook": bool(SHOPIFY_API_SECRET)}


@app.get("/")
async def root():
    return {"service": "hyu-cart", "version": app.version,
            "flavors": sorted(FLAVORS), "tiers": sorted(TIERS), "stats": STATS}


@app.get("/debug/stats")
async def debug_stats():
    return STATS


@app.get("/debug/recent")
async def debug_recent(n: int = 20):
    return list(RECENT)[-max(1, min(n, 80)):]


# ═══════════════════ AUTH DO PAINEL ═══════════════════
# (o /lead + painel /leads foram APOSENTADOS 06/07 — o site não postava mais
#  leads e a aba "Aguardando" do /pedidos cobre carrinho abandonado com dados
#  completos. Histórico exportado: _tmp/leads-hyu-historico-2026-07-06.xlsx.
#  A tabela `leads` permanece no SQLite como arquivo morto.)

_PHONE_RE = re.compile(r"^\d{10,13}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


PANEL_COOKIE = "hyu_panel"
PANEL_TTL = 7 * 86400  # sessão do painel: 7 dias


def _cookie_sig(ts: str) -> str:
    return hmac.new(LEADS_PASSWORD.encode(), f"hyu-panel:{ts}".encode(),
                    hashlib.sha256).hexdigest()[:32]


def _cookie_ok(request: Request) -> bool:
    if not LEADS_PASSWORD:
        return False
    raw = request.cookies.get(PANEL_COOKIE, "")
    ts, _, sig = raw.partition(".")
    if not (ts.isdigit() and sig):
        return False
    if time.time() - int(ts) > PANEL_TTL:
        return False
    return hmac.compare_digest(_cookie_sig(ts), sig)


def _leads_auth(request: Request) -> Response | None:
    """Cookie de sessão do painel OU Basic auth (senha LEADS_PASSWORD) — p/ scripts.
    None = autorizado."""
    if not LEADS_PASSWORD:
        return Response("painel desativado (LEADS_PASSWORD nao configurada)", status_code=503)
    if _cookie_ok(request):
        return None
    auth = request.headers.get("authorization", "")
    if auth.startswith("Basic "):
        try:
            dec = base64.b64decode(auth[6:]).decode("utf-8", "replace")
        except Exception:
            dec = ""
        if dec.split(":", 1)[-1] == LEADS_PASSWORD:
            return None
    return Response("autentique-se", status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="HYU leads"'})


def _panel_auth(request: Request, next_path: str) -> Response | None:
    """Auth das PÁGINAS do painel: sem popup do browser — manda pro /login."""
    from fastapi.responses import RedirectResponse
    if not LEADS_PASSWORD:
        return Response("painel desativado (LEADS_PASSWORD nao configurada)", status_code=503)
    if _cookie_ok(request):
        return None
    auth = request.headers.get("authorization", "")
    if auth.startswith("Basic "):
        try:
            dec = base64.b64decode(auth[6:]).decode("utf-8", "replace")
        except Exception:
            dec = ""
        if dec.split(":", 1)[-1] == LEADS_PASSWORD:
            return None
    return RedirectResponse(f"/login?next={next_path}", status_code=303)


_LOGIN_HTML = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>HYU — Painel</title>
<style>
 *{{box-sizing:border-box}}
 body{{font:15px/1.5 system-ui,sans-serif;margin:0;min-height:100vh;display:flex;
      align-items:center;justify-content:center;background:#111318;color:#eef0f3}}
 .card{{width:min(92vw,380px);background:#1a1d24;border:1px solid #262a33;border-radius:18px;
       padding:2.2rem 2rem;box-shadow:0 18px 50px rgba(0,0,0,.5)}}
 .logo{{display:flex;align-items:center;gap:.6rem;margin-bottom:1.4rem}}
 .logo .dot{{width:38px;height:38px;border-radius:11px;background:#A8CC30;color:#111318;
            display:flex;align-items:center;justify-content:center;font-weight:900;font-size:1.15rem}}
 .logo b{{font-size:1.12rem;letter-spacing:.02em}}
 .logo span{{display:block;font-size:.74rem;color:#8b93a1;font-weight:400}}
 label{{display:block;font-size:.72rem;font-weight:700;text-transform:uppercase;
       letter-spacing:.07em;color:#8b93a1;margin:0 0 .4rem}}
 .pw{{position:relative}}
 input[type=password],input[type=text]{{width:100%;padding:.85rem 3rem .85rem 1rem;font-size:1.05rem;
      background:#111318;color:#eef0f3;border:1px solid #333947;border-radius:12px;outline:none}}
 input:focus{{border-color:#A8CC30;box-shadow:0 0 0 3px rgba(168,204,48,.18)}}
 .eye{{position:absolute;right:.5rem;top:50%;transform:translateY(-50%);border:0;background:none;
      color:#8b93a1;cursor:pointer;font-size:1.1rem;padding:.4rem}}
 button.go{{width:100%;margin-top:1.1rem;padding:.9rem;font-size:1rem;font-weight:800;
      background:#A8CC30;color:#111318;border:0;border-radius:12px;cursor:pointer}}
 button.go:hover{{filter:brightness(1.08)}}
 .err{{background:#3a1d1f;color:#ff9d9d;border:1px solid #5b2a2e;border-radius:10px;
      padding:.6rem .8rem;font-size:.85rem;margin-bottom:1rem}}
 .hint{{margin-top:1.1rem;font-size:.75rem;color:#6b7280;text-align:center}}
</style></head><body>
<form class="card" method="post" action="/login">
 <div class="logo"><div class="dot">H</div><div><b>HYU · Painel</b><span>pedidos &amp; leads</span></div></div>
 {err}
 <label for="pw">Senha de acesso</label>
 <div class="pw">
  <input id="pw" type="password" name="password" autocomplete="current-password" autofocus required>
  <button class="eye" type="button" onclick="var i=document.getElementById('pw');i.type=i.type==='password'?'text':'password';this.textContent=i.type==='password'?'👁':'🙈'">👁</button>
 </div>
 <input type="hidden" name="next" value="{next}">
 <button class="go" type="submit">Entrar →</button>
 <div class="hint">Sessão fica ativa por 7 dias neste dispositivo.</div>
</form></body></html>"""


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    nxt = request.query_params.get("next", "/pedidos")
    if not nxt.startswith("/"):
        nxt = "/pedidos"
    if _cookie_ok(request):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(nxt, status_code=303)
    return HTMLResponse(_LOGIN_HTML.format(err="", next=_esc(nxt)))


@app.post("/login")
async def login_submit(request: Request):
    from fastapi.responses import RedirectResponse
    from urllib.parse import parse_qs
    # form urlencoded parseado na mão (evita dependência python-multipart)
    raw = (await request.body()).decode("utf-8", "replace")
    form = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
    pwd = str(form.get("password") or "")
    nxt = str(form.get("next") or "/pedidos")
    if not nxt.startswith("/"):
        nxt = "/pedidos"
    if not LEADS_PASSWORD:
        return Response("painel desativado", status_code=503)
    if not hmac.compare_digest(pwd, LEADS_PASSWORD):
        await asyncio.sleep(0.7)  # freio anti-bruteforce
        return HTMLResponse(_LOGIN_HTML.format(
            err='<div class="err">Senha incorreta.</div>', next=_esc(nxt)),
            status_code=401)
    ts = str(int(time.time()))
    resp = RedirectResponse(nxt, status_code=303)
    resp.set_cookie(PANEL_COOKIE, f"{ts}.{_cookie_sig(ts)}", max_age=PANEL_TTL,
                    httponly=True, secure=True, samesite="lax", path="/")
    return resp


@app.get("/logout")
async def logout():
    from fastapi.responses import RedirectResponse
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(PANEL_COOKIE, path="/")
    return resp


def _brl(cents: int) -> str:
    return f"R$ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


# ═══════════════════ PEDIDOS (compradores — painel + Excel) ═══════════════════

def _fetch_pedidos() -> list[dict[str, Any]]:
    conn = _db()
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM pedidos ORDER BY id DESC").fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        p = dict(r)
        p["itens"] = json.loads(p.get("items") or "[]")
        p["meta_d"] = json.loads(p.get("meta") or "{}")
        out.append(p)
    return out


def _itens_str(itens: list[dict]) -> str:
    return " + ".join(f"{i['qty']}x {i['name']}" if i.get("qty", 1) > 1 else i["name"]
                      for i in itens)


def _endereco_str(p: dict) -> str:
    comp = f" {p['complement']}" if p.get("complement") else ""
    return (f"{p['street']}, {p['number']}{comp} — {p['neighborhood']}, "
            f"{p['city']}/{p['state']} — CEP {p['cep']}")


# SKU ausente (histórico Paggins não tinha SKU cadastrado) → deriva pelo nome
_SKU_FLAVORS = [("hot lemon", "HOTLEMON"), ("maçã verde", "MACAVERDE"),
                ("maca verde", "MACAVERDE"), ("pêssego", "PESSEGOMORANGO"),
                ("pessego", "PESSEGOMORANGO"), ("maçã vermelha", "MACAVERMELHA"),
                ("maca vermelha", "MACAVERMELHA"), ("tropical", "TROPICAL")]
_SKU_COMBOS = [("super kit", "SUPERKIT"), ("kit energy", "KITENERGY"),
               ("kit soda", "KITSODA"), ("kit 24", "KIT24"), ("kit24", "KIT24")]


def _derive_sku(name: str) -> str:
    n = (name or "").lower()
    sub = "assinatura" in n
    for hint, sku in _SKU_COMBOS:
        if hint in n:
            return f"HYU-SUB-{sku}" if sub else f"HYU-{sku}"
    flavor = next((sku for hint, sku in _SKU_FLAVORS if hint in n), "")
    tier = "K12" if ("kit 12" in n or "12 latas" in n) else \
           "K6" if ("kit 6" in n or "6 latas" in n) else ""
    if sub:
        return f"HYU-SUB-{flavor}" if flavor else "HYU-SUB"
    if flavor and tier:
        return f"HYU-{flavor}-{tier}"
    return ""


def _item_sku(it: dict) -> str:
    return it.get("sku") or _derive_sku(it.get("name", ""))


def _skus_str(itens: list[dict]) -> str:
    return " + ".join(f"{i.get('qty', 1)}x {_item_sku(i) or '?'}" for i in itens)


_PEDIDOS_COLS = ["id", "data_utc", "pago_em_utc", "status", "nome", "cpf", "whatsapp",
                 "email", "endereco", "itens", "skus", "frete_servico", "frete_reais",
                 "subtotal_reais", "total_reais", "cupom", "bling_status",
                 "bling_pedido", "rastreio", "utm_source", "utm_campaign", "gclid"]


def _pedido_export_row(p: dict) -> list:
    m = p["meta_d"]
    return [p["id"], p["ts"], p.get("paid_ts") or "", p["status"], p["name"],
            p["document"], p["phone"], p["email"], _endereco_str(p),
            _itens_str(p["itens"]), _skus_str(p["itens"]),
            p.get("frete_service") or "",
            round((p.get("frete_cents") or 0) / 100, 2),
            round((p.get("subtotal_cents") or 0) / 100, 2),
            round((p.get("total_cents") or 0) / 100, 2),
            p.get("coupon") or "", p.get("bling_status") or "",
            p.get("bling_order_id") or "", p.get("tracking") or "",
            m.get("utm_source", ""), m.get("utm_campaign", ""), m.get("gclid", "")]


def _afiliado_cell(p: dict, com_por_order: dict) -> str:
    """Coluna Afiliado do /pedidos: comissão creditada, ou o alerta de tag/cupom que
    CHEGOU no pedido mas não achou dono (venda que deveria comissionar e não comissionou)."""
    c = com_por_order.get(p.get("order_id") or "")
    if c:
        cls = {"paid": "ok", "reversed": "err"}.get(c["status"], "pend")
        return (f"<span class='tag'>{_esc(c['tag'])}</span> "
                f"<span class='{cls}'>{_brl(c['valor_cents'])}</span>"
                f"<br><span class='muted'>{_esc(c['label'])} · via {_esc(c.get('via') or '?')}</span>")
    orfa = _norm_tag(p.get("meta_d", {}).get("ref")) or _norm_tag(p.get("coupon"))
    if orfa and p.get("status") == "paid":
        return (f"<span class='pend' title='chegou no pedido mas não há afiliado com essa "
                f"tag/cupom cadastrado — venda não comissionada'>{_esc(orfa)} sem dono</span>")
    return "—"


@app.get("/pedidos", response_class=HTMLResponse)
async def pedidos_panel(request: Request):
    denied = _panel_auth(request, "/pedidos")
    if denied:
        return denied
    pedidos = _fetch_pedidos()
    com_por_order = {c["order_id"]: c for c in _fetch_comissoes()}
    pagos = [p for p in pedidos if p["status"] == "paid"]
    n_wait = sum(1 for p in pedidos if p["status"] in ("created", "open"))
    n_err = len(pedidos) - len(pagos) - n_wait
    total_pago = sum(p.get("total_cents") or 0 for p in pagos)
    rows = []
    for p in pedidos:
        st = p["status"]
        grp = "paid" if st == "paid" else ("wait" if st in ("created", "open") else "err")
        badge = {"paid": "<span class='ok'>PAGO</span>",
                 "wait": "<span class='pend'>aguardando</span>",
                 "err": f"<span class='err'>{_esc(st)}</span>"}[grp]
        bl = p.get("bling_status") or "—"
        if bl == "created":
            bl = f"<span class='ok'>#{_esc(p.get('bling_order_id') or '')}</span>"
        elif bl in ("error", "pending"):
            bl = (f"<span class='err' title='{_esc(p.get('bling_error') or '')}'>{bl}</span> "
                  f"<button onclick=\"blingRetry({p['id']},this)\">↻</button>")
        frete = ("grátis" if p.get("frete_service") == "gratis"
                 else f"{_esc(p.get('frete_service') or '—')} {_brl(p.get('frete_cents') or 0)}"
                 if p.get("frete_cents") or p.get("frete_service") else "—")
        itens_html = "".join(
            f"<div>{_esc((str(i.get('qty', 1)) + 'x ') if i.get('qty', 1) > 1 else '')}{_esc(i.get('name', '?'))}"
            f"<br><span class='sku'>{_esc(_item_sku(i) or 'sem SKU')}</span></div>"
            for i in p["itens"]) or "—"
        search = " ".join(str(x) for x in (
            p["id"], p["name"], p["document"], p["phone"], p["email"],
            p.get("coupon"), _itens_str(p["itens"]), _skus_str(p["itens"]),
            p.get("city"), p.get("state"), p.get("cep"),
            p["meta_d"].get("paggins_order", ""))).lower()
        rows.append(
            f"<tr data-grp='{grp}' data-q=\"{_esc(search)}\"><td>{p['id']}</td>"
            f"<td data-ts='{p['ts']}'></td>"
            f"<td>{badge}</td>"
            f"<td><strong>{_esc(p['name'])}</strong><br><span class='muted'>{_esc(p['document'])}</span></td>"
            f"<td><a href='https://wa.me/55{_esc(p['phone'])}' target='_blank'>{_esc(p['phone'])}</a><br>"
            f"<a href='mailto:{_esc(p['email'])}'>{_esc(p['email'])}</a></td>"
            f"<td class='addr'>{_esc(_endereco_str(p))}</td>"
            f"<td class='itens'>{itens_html}</td>"
            f"<td>{frete}</td>"
            f"<td class='r'>{_brl(p.get('total_cents') or 0)}</td>"
            f"<td>{_esc(p.get('coupon') or '—')}</td>"
            f"<td>{_afiliado_cell(p, com_por_order)}</td>"
            f"<td>{bl}</td>"
            f"<td>{_esc(p.get('tracking') or '—')}</td></tr>"
        )
    html = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>Pedidos HYU ({len(pagos)} pagos)</title>
<style>
 body{{font:14px/1.5 system-ui,sans-serif;margin:0;background:#f5f6f8;color:#16191f}}
 header{{display:flex;align-items:center;gap:1rem;padding:.9rem 1.2rem;background:#16191f;color:#fff;position:sticky;top:0;z-index:5}}
 h1{{font-size:1rem;margin:0}} .pill{{background:#A8CC30;color:#16191f;font-weight:800;border-radius:999px;padding:.1rem .6rem}}
 .grow{{flex:1}} a.btn{{background:#fff;color:#16191f;font-weight:700;text-decoration:none;border-radius:8px;padding:.35rem .8rem;margin-left:.4rem;font-size:.85rem}}
 a.out{{background:none;color:#9aa3b0;border:1px solid #3a3f4a}}
 .bar{{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem;padding:.8rem 1.2rem 0}}
 .tab{{border:1px solid #d7dbe0;background:#fff;border-radius:999px;padding:.32rem .85rem;font-size:.82rem;font-weight:700;cursor:pointer;color:#445}}
 .tab.on{{background:#16191f;color:#fff;border-color:#16191f}}
 .tab small{{font-weight:800;opacity:.65;margin-left:.25rem}}
 #q{{flex:1;min-width:220px;max-width:380px;padding:.45rem .8rem;border:1px solid #d7dbe0;border-radius:999px;font:inherit;font-size:.88rem}}
 #q:focus{{outline:2px solid #A8CC30;border-color:#A8CC30}}
 main{{padding:.6rem 1.2rem 1.2rem;overflow-x:auto}}
 table{{border-collapse:collapse;width:100%;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
 th,td{{padding:.55rem .7rem;border-bottom:1px solid #eceef1;text-align:left;vertical-align:top;font-size:.82rem}}
 th{{background:#fafbfc;font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;color:#667}}
 tr:hover td{{background:#fcfde8}} .r{{text-align:right;white-space:nowrap;font-weight:700}}
 .muted{{color:#889;font-size:.75rem}} .total{{margin:.6rem 0 .2rem;color:#445;font-size:.85rem}}
 .addr{{max-width:230px;font-size:.76rem;color:#556}}
 .itens div{{margin-bottom:.3rem}} .itens div:last-child{{margin-bottom:0}}
 .sku{{font-family:ui-monospace,monospace;font-size:.7rem;background:#f0f2f5;color:#556;border-radius:5px;padding:.02rem .35rem}}
 .ok{{background:#e3f5d4;color:#3a6b12;font-weight:700;border-radius:6px;padding:.05rem .4rem;font-size:.72rem}}
 .pend{{background:#fff3d6;color:#8a6100;border-radius:6px;padding:.05rem .4rem;font-size:.72rem;font-weight:700}}
 .err{{background:#fde3e3;color:#a11;font-weight:700;border-radius:6px;padding:.05rem .4rem;font-size:.72rem}}
 button{{cursor:pointer;border:1px solid #ccd;border-radius:6px;background:#fff}}
</style></head><body>
<header><h1>📦 Pedidos HYU</h1><span class="pill">{len(pagos)} pagos</span><span class="grow"></span>
<a class="btn" href="/afiliados">🤝 Afiliados</a>
<a class="btn" href="/pedidos.xlsx">⬇ Excel</a><a class="btn" href="/pedidos.csv">⬇ CSV</a>
<a class="btn out" href="/logout">Sair</a></header>
<div class="bar">
 <button class="tab on" data-f="all">Todos <small>{len(pedidos)}</small></button>
 <button class="tab" data-f="paid">Pagos <small>{len(pagos)}</small></button>
 <button class="tab" data-f="wait">Aguardando <small>{n_wait}</small></button>
 <button class="tab" data-f="err">Erro/outros <small>{n_err}</small></button>
 <input id="q" type="search" placeholder="Buscar: nome, CPF, e-mail, SKU, cidade, cupom…">
</div>
<main><p class="total">Total pago: <strong>{_brl(total_pago)}</strong> · <span id="showing"></span></p>
<table><thead><tr><th>#</th><th>Quando</th><th>Status</th><th>Cliente / CPF</th><th>Contato</th>
<th>Endereço</th><th>Itens / SKU</th><th>Frete</th><th>Total</th><th>Cupom</th><th>Afiliado</th>
<th>Bling</th><th>Rastreio</th></tr></thead>
<tbody id="tb">{''.join(rows) or '<tr><td colspan=13 style="text-align:center;padding:2rem;color:#889">Nenhum pedido ainda.</td></tr>'}</tbody></table></main>
<script>
document.querySelectorAll('[data-ts]').forEach(td=>{{
 td.textContent=new Date(td.dataset.ts).toLocaleString('pt-BR',{{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}});
}});
var F='all',Q='';
function apply(){{
 var n=0;
 document.querySelectorAll('#tb tr[data-grp]').forEach(function(tr){{
  var ok=(F==='all'||tr.dataset.grp===F)&&(!Q||tr.dataset.q.indexOf(Q)>-1);
  tr.style.display=ok?'':'none'; if(ok)n++;
 }});
 document.getElementById('showing').textContent='mostrando '+n+' pedido'+(n===1?'':'s');
}}
document.querySelectorAll('.tab').forEach(function(b){{
 b.addEventListener('click',function(){{
  document.querySelectorAll('.tab').forEach(function(x){{x.classList.remove('on')}});
  b.classList.add('on'); F=b.dataset.f; apply();
 }});
}});
document.getElementById('q').addEventListener('input',function(){{Q=this.value.trim().toLowerCase();apply();}});
apply();
function blingRetry(id,btn){{btn.disabled=true;btn.textContent='…';
 fetch('/pedidos/'+id+'/bling',{{method:'POST'}}).then(r=>r.json())
 .then(j=>{{btn.textContent=j.bling_status==='created'?'✅':'↻';alert('Bling: '+j.bling_status+(j.bling_error?' — '+j.bling_error:''));location.reload();}})
 .catch(()=>{{btn.disabled=false;btn.textContent='↻';}});}}
</script></body></html>"""
    return HTMLResponse(html)


@app.post("/pedidos/purge")
async def pedidos_purge(request: Request):
    """Remove pedidos por lista de ids (Basic auth). Body: {"ids":[1,2,...]}.
    Usado p/ limpar pedidos não-HYU (loja Paggins compartilhada) e testes."""
    denied = _leads_auth(request)
    if denied:
        return denied
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "JSON invalido")
    ids = payload.get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids) or len(ids) > 2000:
        raise HTTPException(400, "ids invalido (lista de inteiros)")
    conn = _db()
    try:
        cur = conn.executemany("DELETE FROM pedidos WHERE id=?", [(i,) for i in ids])
        conn.commit()
        deleted = cur.rowcount if cur.rowcount is not None else len(ids)
    finally:
        conn.close()
    log.info("pedidos purge: %d ids -> removidos", len(ids))
    return {"requested": len(ids), "deleted": deleted}


@app.post("/pedidos/import")
async def pedidos_import(request: Request):
    """Importa pedidos históricos (ex.: export do painel Paggins). Basic auth.
    Body: {"rows":[{...colunas de pedidos...}]}. Dedupe por order_id e session_id.
    Importados NÃO disparam Bling automático (bling_status='')."""
    denied = _leads_auth(request)
    if denied:
        return denied
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "JSON invalido")
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) > 2000:
        raise HTTPException(400, "rows invalido")
    cols = ["ts", "order_id", "session_id", "status", "paid_ts", "name", "document",
            "email", "phone", "cep", "street", "number", "complement",
            "neighborhood", "city", "state", "items", "subtotal_cents",
            "frete_cents", "frete_service", "total_cents", "coupon", "meta",
            "bling_status", "tracking"]
    ins = skip = 0
    conn = _db()
    try:
        for r in rows:
            if not isinstance(r, dict) or not r.get("order_id"):
                skip += 1
                continue
            dup = conn.execute(
                "SELECT 1 FROM pedidos WHERE order_id=? OR (session_id!='' AND session_id=?) LIMIT 1",
                (str(r["order_id"]), str(r.get("session_id") or ""))).fetchone()
            if dup:
                skip += 1
                continue
            vals = [str(r.get(c) or "") if c not in
                    ("subtotal_cents", "frete_cents", "total_cents")
                    else int(r.get(c) or 0) for c in cols]
            conn.execute(
                f"INSERT INTO pedidos ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' * len(cols))})", vals)
            ins += 1
        conn.commit()
    finally:
        conn.close()
    log.info("pedidos import: %d inseridos, %d pulados", ins, skip)
    return {"inserted": ins, "skipped": skip}


@app.get("/pedidos.csv")
async def pedidos_csv(request: Request):
    denied = _leads_auth(request)
    if denied:
        return denied
    buf = io.StringIO()
    buf.write("﻿")  # BOM pro Excel BR abrir certo
    w = csv.writer(buf, delimiter=";")
    w.writerow(_PEDIDOS_COLS)
    for p in _fetch_pedidos():
        row = _pedido_export_row(p)
        row = [str(v).replace(".", ",") if isinstance(v, float) else v for v in row]
        w.writerow(row)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=pedidos-hyu.csv"})


@app.get("/pedidos.xlsx")
async def pedidos_xlsx(request: Request):
    denied = _leads_auth(request)
    if denied:
        return denied
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Pedidos HYU"
    ws.append(_PEDIDOS_COLS)
    for c in ws[1]:
        c.font = Font(bold=True)
    for p in _fetch_pedidos():
        ws.append(_pedido_export_row(p))
    widths = {"A": 5, "B": 20, "C": 20, "D": 8, "E": 24, "F": 13, "G": 13, "H": 26,
              "I": 46, "J": 40, "K": 26, "L": 12, "M": 10, "N": 12, "O": 10, "P": 10,
              "Q": 12, "R": 12, "S": 16, "T": 12, "U": 14, "V": 20}
    for col, wd in widths.items():
        ws.column_dimensions[col].width = wd
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return StreamingResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=pedidos-hyu.xlsx"})


# ═══════════════════ AFILIADOS — painel do gestor + extrato do afiliado ═══════════════════

SITE_URL = os.environ.get("SITE_URL", "https://hyudrinks.com").rstrip("/")


def _afiliado_link(tag: str) -> str:
    return f"{SITE_URL}/?ref={tag}"


def _hold_cutoff() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=HOLD_DAYS)).isoformat(timespec="seconds")


def _fetch_afiliados() -> list[dict[str, Any]]:
    """Afiliados + saldo agregado. 'liberado' = pending com carencia vencida."""
    cut = _hold_cutoff()
    conn = _db()
    try:
        conn.row_factory = sqlite3.Row
        afs = [dict(r) for r in conn.execute(
            "SELECT * FROM afiliados ORDER BY id DESC").fetchall()]
        soma = {r["tag"]: dict(r) for r in conn.execute(
            "SELECT tag, COUNT(*) vendas, "
            "SUM(CASE WHEN status='pending' THEN valor_cents ELSE 0 END) pend, "
            "SUM(CASE WHEN status='pending' AND ts<? THEN valor_cents ELSE 0 END) libr, "
            "SUM(CASE WHEN status='paid' THEN valor_cents ELSE 0 END) pago, "
            "SUM(CASE WHEN status='reversed' THEN valor_cents ELSE 0 END) estr, "
            "SUM(CASE WHEN status<>'reversed' THEN base_cents ELSE 0 END) base, "
            "SUM(CASE WHEN via='link' THEN 1 ELSE 0 END) v_link, "
            "SUM(CASE WHEN via='cupom' THEN 1 ELSE 0 END) v_cupom "
            "FROM comissoes GROUP BY tag", (cut,)).fetchall()}
    finally:
        conn.close()
    for a in afs:
        s = soma.get(a["tag"], {})
        a["vendas"] = s.get("vendas") or 0
        a["pendente_cents"] = (s.get("pend") or 0) - (s.get("libr") or 0)
        a["liberado_cents"] = s.get("libr") or 0
        a["pago_cents"] = s.get("pago") or 0
        a["estornado_cents"] = s.get("estr") or 0
        a["vendido_cents"] = s.get("base") or 0
        a["via_link"] = s.get("v_link") or 0
        a["via_cupom"] = s.get("v_cupom") or 0
        a["link"] = _afiliado_link(a["tag"])
        a["link_cupom"] = f"{SITE_URL}/{a['cupom']}?ref={a['tag']}" if a.get("cupom") else ""
    return afs


def _fetch_comissoes(tag: str = "") -> list[dict[str, Any]]:
    conn = _db()
    try:
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM comissoes"
        args: tuple = ()
        if tag:
            sql += " WHERE tag=?"
            args = (tag,)
        rows = [dict(r) for r in conn.execute(sql + " ORDER BY id DESC", args).fetchall()]
    finally:
        conn.close()
    cut = _hold_cutoff()
    for c in rows:
        if c["status"] == "pending":
            c["label"] = "liberado" if (c["ts"] or "") < cut else f"em carência ({HOLD_DAYS}d)"
        else:
            c["label"] = {"paid": "pago", "reversed": "estornado"}.get(c["status"], c["status"])
    return rows


@app.post("/afiliados/novo")
async def afiliado_novo(request: Request):
    from fastapi.responses import RedirectResponse
    from urllib.parse import parse_qs
    denied = _panel_auth(request, "/afiliados")
    if denied:
        return denied
    raw = (await request.body()).decode("utf-8", "replace")
    f = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
    tag = _norm_tag(f.get("tag"))
    name = str(f.get("name") or "").strip()[:120]
    if len(tag) < 3 or not name:
        return RedirectResponse("/afiliados?err=tag+invalida+(3-20+letras/numeros)+ou+nome+vazio",
                                status_code=303)
    try:
        pct = float(str(f.get("pct") or AFILIADO_PCT).replace(",", "."))
    except ValueError:
        pct = AFILIADO_PCT
    pct = max(0.0, min(pct, 50.0))
    token = secrets.token_urlsafe(12)
    cupom = _norm_tag(f.get("cupom"))
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO afiliados (ts, tag, name, email, phone, pix, pct, token, active, cupom) "
            "VALUES (?,?,?,?,?,?,?,?,1,?)",
            (ts, tag, name, str(f.get("email") or "").strip()[:160],
             re.sub(r"\D", "", str(f.get("phone") or ""))[:13],
             str(f.get("pix") or "").strip()[:140], pct, token, cupom))
        conn.commit()
    except sqlite3.IntegrityError:
        return RedirectResponse(f"/afiliados?err=tag+{tag}+ja+existe", status_code=303)
    finally:
        conn.close()
    log.info("afiliado criado tag=%s pct=%s", tag, pct)
    return RedirectResponse(f"/afiliados?ok={tag}", status_code=303)


@app.post("/afiliados/{tag}/editar")
async def afiliado_editar(tag: str, request: Request):
    """Edita o afiliado já criado. A TAG não muda (links divulgados quebrariam) —
    campos editáveis: nome, cupom, PIX, e-mail, WhatsApp e %."""
    from fastapi.responses import RedirectResponse
    from urllib.parse import parse_qs
    denied = _panel_auth(request, "/afiliados")
    if denied:
        return denied
    t = _norm_tag(tag)
    raw = (await request.body()).decode("utf-8", "replace")
    f = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
    name = str(f.get("name") or "").strip()[:120]
    if not name:
        return RedirectResponse("/afiliados?err=nome+nao+pode+ficar+vazio", status_code=303)
    cupom = _norm_tag(f.get("cupom"))
    try:
        pct = float(str(f.get("pct") or AFILIADO_PCT).replace(",", "."))
    except ValueError:
        pct = AFILIADO_PCT
    pct = max(0.0, min(pct, 50.0))
    conn = _db()
    try:
        if not conn.execute("SELECT 1 FROM afiliados WHERE tag=?", (t,)).fetchone():
            return RedirectResponse(f"/afiliados?err=afiliado+{t}+nao+existe", status_code=303)
        if cupom:
            dono = conn.execute(
                "SELECT tag FROM afiliados WHERE cupom=? AND tag<>?", (cupom, t)).fetchone()
            if dono:
                return RedirectResponse(
                    f"/afiliados?err=cupom+{cupom}+ja+e+do+afiliado+{dono[0]}", status_code=303)
        conn.execute(
            "UPDATE afiliados SET name=?, cupom=?, pix=?, email=?, phone=?, pct=? WHERE tag=?",
            (name, cupom, str(f.get("pix") or "").strip()[:140],
             str(f.get("email") or "").strip()[:160],
             re.sub(r"\D", "", str(f.get("phone") or ""))[:13], pct, t))
        conn.commit()
    finally:
        conn.close()
    log.info("afiliado editado tag=%s cupom=%s pct=%s", t, cupom or "-", pct)
    return RedirectResponse(f"/afiliados?ok=afiliado+{t}+atualizado", status_code=303)


@app.post("/afiliados/{tag}/toggle")
async def afiliado_toggle(tag: str, request: Request):
    from fastapi.responses import RedirectResponse
    denied = _panel_auth(request, "/afiliados")
    if denied:
        return denied
    conn = _db()
    try:
        conn.execute("UPDATE afiliados SET active=1-active WHERE tag=?", (_norm_tag(tag),))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/afiliados", status_code=303)


@app.post("/afiliados/{tag}/pagar")
async def afiliado_pagar(tag: str, request: Request):
    """Marca como PAGAS as comissoes liberadas (carencia vencida) do afiliado.
    O PIX em si e feito por fora — isto so baixa o saldo."""
    from fastapi.responses import RedirectResponse
    denied = _panel_auth(request, "/afiliados")
    if denied:
        return denied
    t = _norm_tag(tag)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = _db()
    try:
        cur = conn.execute(
            "UPDATE comissoes SET status='paid', paid_ts=? "
            "WHERE tag=? AND status='pending' AND ts<?", (ts, t, _hold_cutoff()))
        conn.commit()
        n = cur.rowcount
    finally:
        conn.close()
    log.info("afiliado %s: %s comissoes marcadas como pagas", t, n)
    return RedirectResponse(f"/afiliados?ok=pagas+{n}+comissoes+de+{t}", status_code=303)


@app.get("/afiliados.csv")
async def afiliados_csv(request: Request):
    denied = _leads_auth(request)
    if denied:
        return denied
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf, delimiter=";")
    w.writerow(["tag", "cupom", "afiliado", "pix", "email", "whatsapp", "pct", "vendas",
                "vendas_por_link", "vendas_por_cupom",
                "vendido_reais", "pendente_reais", "liberado_reais", "pago_reais", "link"])
    for a in _fetch_afiliados():
        w.writerow([a["tag"], a.get("cupom") or "", a["name"], a.get("pix") or "",
                    a.get("email") or "",
                    a.get("phone") or "", a.get("pct"), a["vendas"],
                    a["via_link"], a["via_cupom"],
                    str(round(a["vendido_cents"] / 100, 2)).replace(".", ","),
                    str(round(a["pendente_cents"] / 100, 2)).replace(".", ","),
                    str(round(a["liberado_cents"] / 100, 2)).replace(".", ","),
                    str(round(a["pago_cents"] / 100, 2)).replace(".", ","), a["link"]])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=afiliados-hyu.csv"})


_AF_CSS = """
 body{font:14px/1.5 system-ui,sans-serif;margin:0;background:#f5f6f8;color:#16191f}
 header{display:flex;align-items:center;gap:1rem;padding:.9rem 1.2rem;background:#16191f;color:#fff;position:sticky;top:0;z-index:5}
 h1{font-size:1rem;margin:0} .pill{background:#A8CC30;color:#16191f;font-weight:800;border-radius:999px;padding:.1rem .6rem}
 .grow{flex:1} a.btn{background:#fff;color:#16191f;font-weight:700;text-decoration:none;border-radius:8px;padding:.35rem .8rem;margin-left:.4rem;font-size:.85rem}
 a.out{background:none;color:#9aa3b0;border:1px solid #3a3f4a}
 main{padding:1rem 1.2rem 2rem;overflow-x:auto;max-width:1200px}
 table{border-collapse:collapse;width:100%;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08)}
 th,td{padding:.55rem .7rem;border-bottom:1px solid #eceef1;text-align:left;font-size:.82rem;vertical-align:top}
 th{background:#fafbfc;font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;color:#667}
 tr:hover td{background:#fcfde8} .r{text-align:right;white-space:nowrap;font-weight:700}
 .muted{color:#889;font-size:.75rem} .off{opacity:.45}
 .tag{font-family:ui-monospace,monospace;font-weight:800;background:#16191f;color:#A8CC30;border-radius:6px;padding:.1rem .45rem}
 .lnk{font-family:ui-monospace,monospace;font-size:.72rem;color:#556;word-break:break-all}
 .ok{background:#e3f5d4;color:#3a6b12;font-weight:700;border-radius:6px;padding:.05rem .4rem;font-size:.72rem}
 .pend{background:#fff3d6;color:#8a6100;border-radius:6px;padding:.05rem .4rem;font-size:.72rem;font-weight:700}
 .err{background:#fde3e3;color:#a11;font-weight:700;border-radius:6px;padding:.05rem .4rem;font-size:.72rem}
 form.new{background:#fff;border-radius:12px;padding:1rem;margin-bottom:1rem;box-shadow:0 1px 4px rgba(0,0,0,.08);
   display:flex;flex-wrap:wrap;gap:.5rem;align-items:flex-end}
 form.new label{display:flex;flex-direction:column;font-size:.7rem;text-transform:uppercase;color:#667;font-weight:700;gap:.2rem}
 form.new input{padding:.45rem .6rem;border:1px solid #d7dbe0;border-radius:8px;font:inherit;font-size:.85rem}
 form.new input:focus{outline:2px solid #A8CC30;border-color:#A8CC30}
 button{cursor:pointer;border:0;border-radius:8px;background:#A8CC30;color:#16191f;font-weight:800;padding:.5rem .9rem;font-size:.85rem}
 button.gh{background:#eef0f3;color:#445;font-weight:700;padding:.25rem .55rem;font-size:.75rem}
 .msg{padding:.6rem .9rem;border-radius:10px;margin-bottom:.8rem;font-size:.85rem}
 .msg.o{background:#e3f5d4;color:#3a6b12} .msg.e{background:#fde3e3;color:#a11}
 .cards{display:flex;flex-wrap:wrap;gap:.7rem;margin-bottom:1rem}
 .card{background:#fff;border-radius:12px;padding:.8rem 1.1rem;box-shadow:0 1px 4px rgba(0,0,0,.08);min-width:150px}
 .card b{display:block;font-size:1.35rem;font-family:ui-monospace,monospace} .card span{font-size:.72rem;color:#778;text-transform:uppercase;font-weight:700}
"""


@app.get("/debug/afiliados")
async def debug_afiliados(request: Request):
    """Saúde do banco de afiliados: colunas (prova que a migração aplicou), contagens e
    as vendas pagas cuja tag/cupom NÃO achou dono (comissão que deixou de ser creditada)."""
    denied = _leads_auth(request)
    if denied:
        return denied
    conn = _db()
    try:
        conn.row_factory = sqlite3.Row
        cols_a = [r[1] for r in conn.execute("PRAGMA table_info(afiliados)")]
        cols_c = [r[1] for r in conn.execute("PRAGMA table_info(comissoes)")]
        por_status = {r[0]: r[1] for r in conn.execute(
            "SELECT status, COUNT(*) FROM comissoes GROUP BY status")}
        por_via = {r[0] or "?": r[1] for r in conn.execute(
            "SELECT via, COUNT(*) FROM comissoes GROUP BY via")}
        n_af = conn.execute("SELECT COUNT(*) FROM afiliados").fetchone()[0]
        tags = {r[0] for r in conn.execute("SELECT tag FROM afiliados")}
        cupons = {r[0] for r in conn.execute(
            "SELECT cupom FROM afiliados WHERE cupom IS NOT NULL AND cupom<>''")}
        com_orders = {r[0] for r in conn.execute("SELECT order_id FROM comissoes")}
        pagos = conn.execute(
            "SELECT order_id, coupon, meta, ts FROM pedidos WHERE status='paid'").fetchall()
    finally:
        conn.close()
    orfas = []
    for p in pagos:
        if p["order_id"] in com_orders:
            continue
        ref = _norm_tag((json.loads(p["meta"] or "{}")).get("ref"))
        cup = _norm_tag(p["coupon"])
        if (ref and ref not in tags) or (cup and cup not in cupons and cup not in tags):
            orfas.append({"order_id": p["order_id"], "ts": p["ts"],
                          "ref": ref or None, "cupom": cup or None})
    return {
        "schema_ok": "cupom" in cols_a and "via" in cols_c,
        "colunas_afiliados": cols_a, "colunas_comissoes": cols_c,
        "afiliados": n_af, "comissoes_por_status": por_status, "comissoes_por_via": por_via,
        "pedidos_pagos": len(pagos), "pedidos_com_comissao": len(com_orders),
        "vendas_sem_dono": orfas[:50],
        "obs": ("vendas_sem_dono = pedido pago com tag/cupom que não tem afiliado "
                "cadastrado; cadastrar a tag NÃO credita retroativo"),
    }


def _edit_row(a: dict) -> str:
    """Linha oculta com o form de edição do afiliado (a tag não é editável)."""
    tag = _esc(a["tag"])
    cup = (a.get("cupom") or "").upper()
    # cupom que o SITE não conhece atribui a venda mas NÃO dá desconto ao cliente
    aviso = ("" if not cup or cup in INFLUENCER_COUPONS else
             f"<span class='err' title='o site não tem esse cupom em INFLUENCER_COUPONS — "
             f"ele atribui a venda mas NÃO aplica desconto'>⚠ {_esc(cup)} não dá desconto</span>")
    opts = "".join(f"<option value='{_esc(k)}'>" for k in sorted(INFLUENCER_COUPONS))
    return (
        f"<tr id='ed-{tag}' hidden><td colspan='11' style='background:#fafbfc'>"
        f"<form class='new' method='post' action='/afiliados/{tag}/editar' "
        f"style='box-shadow:none;margin:0'>"
        f"<label>Tag (fixa)<input value='{tag}' disabled style='background:#eef0f3'></label>"
        f"<label>Nome<input name='name' value=\"{_esc(a.get('name') or '')}\" required></label>"
        f"<label>Cupom<input name='cupom' value='{_esc(cup)}' list='cupons-{tag}' "
        f"placeholder='ARTHURPC'><datalist id='cupons-{tag}'>{opts}</datalist></label>"
        f"<label>Chave PIX<input name='pix' value=\"{_esc(a.get('pix') or '')}\"></label>"
        f"<label>E-mail<input name='email' type='email' value=\"{_esc(a.get('email') or '')}\"></label>"
        f"<label>WhatsApp<input name='phone' value=\"{_esc(a.get('phone') or '')}\"></label>"
        f"<label>%<input name='pct' value='{a.get('pct') or AFILIADO_PCT:g}' size='4'></label>"
        f"<button type='submit'>Salvar</button> {aviso}</form></td></tr>")


@app.get("/afiliados", response_class=HTMLResponse)
async def afiliados_panel(request: Request):
    denied = _panel_auth(request, "/afiliados")
    if denied:
        return denied
    afs = _fetch_afiliados()
    ok = request.query_params.get("ok", "")
    err = request.query_params.get("err", "")
    msg = (f'<div class="msg o">✓ {_esc(ok)}</div>' if ok else "") + \
          (f'<div class="msg e">⚠ {_esc(err)}</div>' if err else "")
    tot_lib = sum(a["liberado_cents"] for a in afs)
    tot_pend = sum(a["pendente_cents"] for a in afs)
    tot_pago = sum(a["pago_cents"] for a in afs)
    tot_vend = sum(a["vendido_cents"] for a in afs)
    rows = []
    for a in afs:
        off = "" if a.get("active") else " class='off'"
        extrato = f"/a/{a['tag']}?k={a.get('token') or ''}"
        divulga = a["link_cupom"] or a["link"]      # com cupom = desconto + comissão no mesmo link
        cup_lbl = (f"<br><span class='muted'>cupom {_esc(a['cupom'])}</span>"
                   if a.get("cupom") else "")
        rows.append(
            f"<tr{off}><td><span class='tag'>{_esc(a['tag'])}</span>"
            f"{'' if a.get('active') else ' <span class=err>inativo</span>'}{cup_lbl}</td>"
            f"<td><strong>{_esc(a['name'])}</strong><br>"
            f"<span class='muted'>{_esc(a.get('email') or '')} {_esc(a.get('phone') or '')}</span></td>"
            f"<td><span class='lnk'>{_esc(divulga)}</span><br>"
            f"<button class='gh' onclick=\"navigator.clipboard.writeText('{_esc(divulga)}');"
            f"this.textContent='copiado ✓'\">copiar link</button> "
            f"<a class='gh' href='{_esc(extrato)}' target='_blank'><button class='gh'>extrato</button></a></td>"
            f"<td>{_esc(a.get('pix') or '—')}</td>"
            f"<td class='r'>{a['pct']:g}%</td>"
            f"<td class='r'>{a['vendas']}"
            f"<br><span class='muted' style='font-weight:400'>{a['via_link']} link · {a['via_cupom']} cupom</span></td>"
            f"<td class='r'>{_brl(a['vendido_cents'])}</td>"
            f"<td class='r'><span class='pend'>{_brl(a['pendente_cents'])}</span></td>"
            f"<td class='r'><span class='ok'>{_brl(a['liberado_cents'])}</span></td>"
            f"<td class='r muted'>{_brl(a['pago_cents'])}</td>"
            f"<td><form method='post' action='/afiliados/{_esc(a['tag'])}/pagar' style='display:inline'>"
            f"<button class='gh'>✓ pagar</button></form> "
            f"<button class='gh' onclick=\"var e=document.getElementById('ed-{_esc(a['tag'])}');"
            f"e.hidden=!e.hidden\">✎ editar</button> "
            f"<form method='post' action='/afiliados/{_esc(a['tag'])}/toggle' style='display:inline'>"
            f"<button class='gh'>{'pausar' if a.get('active') else 'ativar'}</button></form></td></tr>"
            f"{_edit_row(a)}")
    tbody = "".join(rows) or ("<tr><td colspan='11' class='muted' style='padding:1.2rem'>"
                              "Nenhum afiliado ainda — cadastre acima.</td></tr>")
    html = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>Afiliados HYU ({len(afs)})</title><style>{_AF_CSS}</style></head><body>
<header><h1>🤝 Afiliados HYU</h1><span class="pill">{len(afs)}</span><span class="grow"></span>
<a class="btn" href="/pedidos">📦 Pedidos</a><a class="btn" href="/afiliados.csv">⬇ CSV</a>
<a class="btn out" href="/logout">Sair</a></header>
<main>
{msg}
<div class="cards">
 <div class="card"><span>a pagar (liberado)</span><b>{_brl(tot_lib)}</b></div>
 <div class="card"><span>em carência {HOLD_DAYS}d</span><b>{_brl(tot_pend)}</b></div>
 <div class="card"><span>já pago</span><b>{_brl(tot_pago)}</b></div>
 <div class="card"><span>vendido por afiliados</span><b>{_brl(tot_vend)}</b></div>
</div>
<form class="new" method="post" action="/afiliados/novo">
 <label>Tag (o código do link)<input name="tag" placeholder="ARTHUR" required></label>
 <label>Nome<input name="name" placeholder="Arthur Silva" required></label>
 <label>Cupom de desconto (opcional)<input name="cupom" placeholder="ARTHURPC"></label>
 <label>Chave PIX<input name="pix" placeholder="cpf/email/telefone"></label>
 <label>E-mail<input name="email" type="email"></label>
 <label>WhatsApp<input name="phone" placeholder="41999999999"></label>
 <label>%<input name="pct" value="{AFILIADO_PCT:g}" size="4"></label>
 <button type="submit">+ Criar afiliado</button>
</form>
<table><thead><tr><th>Tag</th><th>Afiliado</th><th>Link de divulgação</th><th>PIX</th><th>%</th>
<th>Vendas</th><th>Vendido</th><th>Carência</th><th>A pagar</th><th>Pago</th><th></th></tr></thead>
<tbody>{tbody}</tbody></table>
<p class="muted" style="margin-top:1rem">Comissão = {AFILIADO_PCT:g}% do subtotal de produtos
(sem frete, após cupom), creditada quando o pedido é <b>pago</b> e liberada {HOLD_DAYS} dias depois
(janela de estorno). "✓ pagar" só dá baixa no saldo — o PIX é feito por fora.<br>
<b>Cupom × tag:</b> o cupom dá desconto ao cliente; a tag credita a comissão. Preenchendo o campo
Cupom, o link de divulgação vira <code>/CUPOM?ref=TAG</code> (as duas coisas de uma vez) e a venda
é atribuída mesmo quando o cliente só digita o cupom no checkout — a coluna Vendas mostra a
quebra <i>link · cupom</i>.</p>
</main></body></html>"""
    return HTMLResponse(html)


@app.get("/a/{tag}", response_class=HTMLResponse)
async def afiliado_extrato(tag: str, request: Request, k: str = ""):
    """Extrato read-only do afiliado (link com token — sem senha, sem dados do comprador)."""
    t = _norm_tag(tag)
    conn = _db()
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM afiliados WHERE tag=?", (t,)).fetchone()
    finally:
        conn.close()
    if not row or not k or not hmac.compare_digest(k, str(row["token"] or "")):
        return HTMLResponse("<h1>Link inválido</h1>", status_code=404)
    a = dict(row)
    com = _fetch_comissoes(t)
    lib = sum(c["valor_cents"] for c in com if c["label"] == "liberado")
    car = sum(c["valor_cents"] for c in com if c["label"].startswith("em carência"))
    pago = sum(c["valor_cents"] for c in com if c["status"] == "paid")
    link = (f"{SITE_URL}/{a['cupom']}?ref={t}" if a.get("cupom") else _afiliado_link(t))
    rows = "".join(
        f"<tr><td>{_esc((c['ts'] or '')[:10])}</td>"
        f"<td class='muted'>{_esc('cupom' if c.get('via') == 'cupom' else 'link')}</td>"
        f"<td class='r'>{_brl(c['base_cents'])}</td><td class='r'>{c['pct']:g}%</td>"
        f"<td class='r'>{_brl(c['valor_cents'])}</td>"
        f"<td><span class='{'ok' if c['label'] in ('liberado', 'pago') else 'err' if c['status'] == 'reversed' else 'pend'}'>"
        f"{_esc(c['label'])}</span></td></tr>" for c in com) or \
        "<tr><td colspan='6' class='muted' style='padding:1.2rem'>Nenhuma venda ainda — divulgue seu link!</td></tr>"
    html = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>HYU · Afiliado {_esc(a['name'])}</title><style>{_AF_CSS}</style></head><body>
<header><h1>🤝 HYU · {_esc(a['name'])}</h1><span class="pill">{a['pct']:g}%</span></header>
<main>
<div class="cards">
 <div class="card"><span>a receber</span><b>{_brl(lib)}</b></div>
 <div class="card"><span>em carência {HOLD_DAYS}d</span><b>{_brl(car)}</b></div>
 <div class="card"><span>já recebido</span><b>{_brl(pago)}</b></div>
 <div class="card"><span>vendas</span><b>{len([c for c in com if c['status'] != 'reversed'])}</b></div>
</div>
<div class="card" style="margin-bottom:1rem">
 <span>seu link de divulgação</span>
 <p class="lnk" style="margin:.3rem 0">{_esc(link)}</p>
 <button onclick="navigator.clipboard.writeText('{_esc(link)}');this.textContent='copiado ✓'">copiar link</button>
</div>
<table><thead><tr><th>Data</th><th>Origem</th><th>Venda</th><th>%</th><th>Comissão</th><th>Status</th></tr></thead>
<tbody>{rows}</tbody></table>
<p class="muted" style="margin-top:1rem">Comissão sobre os produtos (sem frete), liberada
{HOLD_DAYS} dias após o pagamento. Pedido cancelado/estornado não gera comissão.</p>
</main></body></html>"""
    return HTMLResponse(html)
