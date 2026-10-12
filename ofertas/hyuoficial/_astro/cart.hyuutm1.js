/* HYU cart hyuutm1 — base hyumix6 + UTMs persistidas e coladas na URL do checkout.
 * HYU cart v3.2 (hyumix4) — reescrita legível do cart.D0a-thWQ.js + KIT PERSONALIZADO.
 *
 * Item do carrinho (localStorage hyu-cart-v2):
 *   {flavor, tier, qty}                 kit de 1 sabor (ou combo: flavor=slug do combo)
 *   {mix:{slug:latas,...}, tier, qty}   kit personalizado — soma das latas fecha o kit;
 *                                       preço = kit + MIX_FEE (R$4,90). 1 sabor só
 *                                       colapsa pra kit normal sem taxa.
 * Exports mantêm as MESMAS letras do módulo antigo (Header/StickyBuy/obrigado
 * importam por letra); novos: t=addMix u=lineKey v=removeByKey w=setQtyByKey
 * y=MIX_FEE z=unitCents. /_astro/ é immutable — arquivo NOVO, não editar o velho.
 */
const FLAVORS = [
  { line: "energy", flavor: "Maçã Vermelha", slug: "maca-vermelha", color: "#CC5454", desc: "Maçã vermelha bem madura" },
  { line: "protein", flavor: "Maçã Verde", slug: "maca-verde", color: "#3CC0E4", desc: "Maçã verde crocante e ácida" },
  { line: "energy", flavor: "Tropical", slug: "tropical", color: "#E4A83C", desc: "Abacaxi, manga e maracujá" },
  { line: "protein", flavor: "Pêssego com Morango", slug: "pessego-morango", color: "#EE7C3C", desc: "Pêssego doce com morango" },
  { line: "protein", flavor: "Hot Lemon", slug: "hot-lemon", color: "#A8CC30", desc: "Limão com um quê picante", signature: !0 },
];
const TIERS = {
  kit6: { label: "Kit 6", cans: 6, price: "R$ 69,90", cents: 6990, save: "R$ 11,65 / lata", freeShip: !1 },
  kit12: { label: "Kit 12", cans: 12, price: "R$ 119,90", cents: 11990, save: "R$ 9,99 / lata", freeShip: !0, best: !0 },
  kit24: { label: "Kit 24", cans: 24, price: "R$ 219,90", cents: 21990, save: "R$ 9,16 / lata", freeShip: !0 },
  sub: { label: "Assinatura", cans: 12, price: "R$ 99,90", cents: 9990, save: "R$ 8,33 / lata", freeShip: !0 },
};
const COMBOS_META = [
  { slug: "kit-energy", title: "Kit Energy", sub: "3 Maçã Vermelha + 3 Tropical", tier: "kit6", color: "#E4A83C", items: [{ flavor: "maca-vermelha", qty: 3 }, { flavor: "tropical", qty: 3 }] },
  { slug: "kit-soda", title: "Kit Soda", sub: "3 Maçã Verde + 3 Pêssego com Morango", tier: "kit6", color: "#3CC0E4", items: [{ flavor: "maca-verde", qty: 3 }, { flavor: "pessego-morango", qty: 3 }] },
  { slug: "super-kit", title: "Super Kit", sub: "Os 4 sabores · 12 latas", tier: "kit12", color: "#A8CC30", best: !0, items: [{ flavor: "maca-vermelha", qty: 3 }, { flavor: "tropical", qty: 3 }, { flavor: "maca-verde", qty: 3 }, { flavor: "pessego-morango", qty: 3 }] },
  { slug: "kit24", title: "Kit 24", sub: "2× Super Kit · os 4 sabores · 24 latas", tier: "kit24", color: "#c4f439", hidden: !0, img: "super-kit", items: [{ flavor: "maca-vermelha", qty: 8 }, { flavor: "maca-verde", qty: 8 }, { flavor: "tropical", qty: 8 }] },
  { slug: "assinatura", title: "Assinatura · Super Kit", sub: "Os 4 sabores · 12 latas todo mês", tier: "sub", color: "#A8CC30", hidden: !0, img: "super-kit", items: [{ flavor: "maca-vermelha", qty: 4 }, { flavor: "maca-verde", qty: 4 }, { flavor: "tropical", qty: 4 }] },
  { slug: "assinatura-kit-energy", title: "Assinatura · Kit Energy", sub: "6 Maçã Vermelha + 6 Tropical todo mês", tier: "sub", color: "#E4A83C", hidden: !0, img: "kit-energy", items: [{ flavor: "maca-vermelha", qty: 6 }, { flavor: "tropical", qty: 6 }] },
  { slug: "assinatura-kit-soda", title: "Assinatura · Kit Soda", sub: "4 Hot Lemon + 4 Pêssego & Morango + 4 Maçã Verde todo mês", tier: "sub", color: "#3CC0E4", hidden: !0, img: "kit-soda", items: [{ flavor: "hot-lemon", qty: 4 }, { flavor: "pessego-morango", qty: 4 }, { flavor: "maca-verde", qty: 4 }] },
  { slug: "assinatura-hot-lemon", title: "Assinatura · Hot Lemon", sub: "12× Hot Lemon todo mês", tier: "sub", color: "#A8CC30", hidden: !0, img: "hot-lemon", items: [{ flavor: "hot-lemon", qty: 12 }] },
  { slug: "assinatura-maca-verde", title: "Assinatura · Maçã Verde", sub: "12× Maçã Verde todo mês", tier: "sub", color: "#3CC0E4", hidden: !0, img: "maca-verde", items: [{ flavor: "maca-verde", qty: 12 }] },
  { slug: "assinatura-pessego-morango", title: "Assinatura · Pêssego com Morango", sub: "12× Pêssego com Morango todo mês", tier: "sub", color: "#EE7C3C", hidden: !0, img: "pessego-morango", items: [{ flavor: "pessego-morango", qty: 12 }] },
  { slug: "assinatura-tropical", title: "Assinatura · Tropical", sub: "12× Tropical todo mês", tier: "sub", color: "#E4A83C", hidden: !0, img: "tropical", items: [{ flavor: "tropical", qty: 12 }] },
  { slug: "assinatura-maca-vermelha", title: "Assinatura · Maçã Vermelha", sub: "12× Maçã Vermelha todo mês", tier: "sub", color: "#CC5454", hidden: !0, img: "maca-vermelha", items: [{ flavor: "maca-vermelha", qty: 12 }] },
];
const BASE = "https://www.paggins.com/checkout/";
const LINKS = {
  "hot-lemon": { unit: `${BASE}a63d020f-92cf-4565-8858-0e15be03f3d7`, kit6: `${BASE}8534bbc5-5a43-46e2-9551-89d26d84c22f`, kit12: `${BASE}95e0f88f-6fca-4a19-89a1-9583c93e09df` },
  "maca-verde": { unit: `${BASE}b49ee6fb-78c2-4327-8048-49f707d92ece`, kit6: `${BASE}a585f927-16c4-47ae-a13b-980b3c55601e`, kit12: `${BASE}909baad1-bd89-4e28-ab14-4f3793fbabea` },
  "pessego-morango": { unit: `${BASE}f1b33825-9ca0-454a-a553-024a22e9f345`, kit6: `${BASE}1cf46530-8d6a-4feb-a1c9-cacfd0b93481`, kit12: `${BASE}7ff35585-7f89-4c11-b67a-b564e601a820` },
  tropical: { unit: `${BASE}9dfc2557-bf1d-4a15-9988-d705dcbbe8f8`, kit6: `${BASE}e3fc8cae-ed54-4b22-8d67-2e914eadb14e`, kit12: `${BASE}ee27af7e-cc0f-4212-b162-692776fd7f09` },
  "maca-vermelha": { unit: `${BASE}878046fc-cb6e-446b-ab19-636c503668e8`, kit6: `${BASE}6595de07-23c2-44b7-bf99-d2f00919be96`, kit12: `${BASE}d8d1b025-bb9f-4b80-92c0-76845a01453c` },
};
const COMBO_LINKS = {
  "kit-energy": { tier: "kit6", url: `${BASE}5287a35b-9a4c-4307-a929-599ab5e2791d` },
  "kit-soda": { tier: "kit6", url: `${BASE}62ed2805-089e-454f-afa0-f28f6dfa6abc` },
  "super-kit": { tier: "kit12", url: `${BASE}972ac99f-2800-4db9-88af-d34246cbd3ed` },
  kit24: { tier: "kit24", url: `${BASE}35818f74-5267-46d6-98f7-c19badd7cea7` },
  assinatura: { tier: "sub", url: `${BASE}c174e3a9-bbc1-48af-a617-5290388db37b` },
  "assinatura-kit-energy": { tier: "sub", url: `${BASE}b0a52329-fdb3-4d50-beaf-7f9ee2209898` },
  "assinatura-kit-soda": { tier: "sub", url: `${BASE}db91e65c-9fb6-4328-8027-5f8e5145d86a` },
  "assinatura-hot-lemon": { tier: "sub", url: `${BASE}8dd9a6ee-c2b1-47fd-852a-a477860a8a6f` },
  "assinatura-maca-verde": { tier: "sub", url: `${BASE}cbdcb35a-6d1c-43e7-b62d-9c9a152eb602` },
  "assinatura-pessego-morango": { tier: "sub", url: `${BASE}10369cb4-848f-41e7-9814-be3ea9088152` },
  "assinatura-tropical": { tier: "sub", url: `${BASE}bb3a84b4-2cb0-41f9-9d2c-35e3ddb42da8` },
  "assinatura-maca-vermelha": { tier: "sub", url: `${BASE}6c812a5f-2113-4c03-996c-4c1bd679ee0d` },
};
for (const [slug, meta] of Object.entries(COMBO_LINKS))
  if (meta.url) LINKS[slug] = { [meta.tier]: meta.url };

const LS = "hyu-cart-v2", LS_OLD = "hyu-cart-v1";
const TIERS_OK = ["kit6", "kit12", "kit24", "sub"];
const MAX_QTY = 20, MAX_LINES = 10;
const COMBO_SET = new Set(["kit-energy", "kit-soda", "super-kit", "kit24"]);
const API = "https://cart.hyudrinks.com";

/* kit personalizado — manter em sincronia com o bridge (MIX_FEE_CENTS) */
const MIX_FEE = 490;
const MIX_STEP = 1;   // latas por toque: escolha livre, lata a lata
const MIX_TIERS = { kit6: 6, kit12: 12 };
const FLAVOR_SET = new Set(FLAVORS.map((f) => f.slug));

function validMix(it) {
  if (!it || typeof it !== "object" || !it.mix || typeof it.mix !== "object") return !1;
  if (!(it.tier in MIX_TIERS)) return !1;
  if (!Number.isInteger(it.qty) || it.qty < 1 || it.qty > MAX_QTY) return !1;
  let total = 0;
  const keys = Object.keys(it.mix);
  if (!keys.length) return !1;
  for (const slug of keys) {
    const n = it.mix[slug];
    if (!FLAVOR_SET.has(slug) || !Number.isInteger(n) || n < MIX_STEP || n % MIX_STEP) return !1;
    total += n;
  }
  return total === MIX_TIERS[it.tier];
}
function validItem(it) {
  if (it && typeof it === "object" && it.mix) return validMix(it);
  return !!it && typeof it === "object" && TIERS_OK.includes(it.tier) &&
    !!LINKS[it.flavor]?.[it.tier] && Number.isInteger(it.qty) &&
    it.qty >= 1 && it.qty <= MAX_QTY;
}
function mixKeyOf(mix) {
  return Object.keys(mix).sort().map((s) => `${s}.${mix[s]}`).join("_");
}
function lineKey(it) {
  return it.mix ? `mix:${it.tier}:${mixKeyOf(it.mix)}` : `${it.flavor}:${it.tier}`;
}
function unitCents(it) {
  return TIERS[it.tier].cents + (it.mix ? MIX_FEE : 0);
}

function save(cart) {
  localStorage.setItem(LS, JSON.stringify(cart));
  window.dispatchEvent(new CustomEvent("hyu:cart", { detail: cart }));
  return cart;
}
function read() {
  try {
    const c = JSON.parse(localStorage.getItem(LS) || "");
    if (Array.isArray(c?.items)) return { items: c.items.filter(validItem).slice(0, MAX_LINES) };
  } catch {}
  try {
    const old = JSON.parse(localStorage.getItem(LS_OLD) || "");
    if (LINKS[old?.flavor] && TIERS_OK.includes(old?.tier)) {
      localStorage.removeItem(LS_OLD);
      const cart = { items: [{ flavor: old.flavor, tier: old.tier, qty: 1 }] };
      localStorage.setItem(LS, JSON.stringify(cart));
      return cart;
    }
  } catch {}
  return { items: [] };
}
function add(flavor, tier, step = 1) {
  if (!LINKS[flavor]?.[tier]) return read();
  if (tier === "sub") return save({ items: [{ flavor, tier, qty: 1 }] });
  const items = read().items.filter((i) => i.tier !== "sub");
  const line = items.find((i) => !i.mix && i.flavor === flavor && i.tier === tier && !i.done);
  if (line) line.qty = Math.min(line.qty + step, MAX_QTY);
  else if (items.length < MAX_LINES)
    items.push({ flavor, tier, qty: Math.min(Math.max(step, 1), MAX_QTY) });
  return save({ items });
}
function addMix(mix, tier) {
  const counts = {};
  for (const slug of Object.keys(mix || {})) {
    const n = mix[slug] | 0;
    if (FLAVOR_SET.has(slug) && n >= MIX_STEP && n % MIX_STEP === 0) counts[slug] = n;
  }
  const slugs = Object.keys(counts);
  const total = slugs.reduce((s, k) => s + counts[k], 0);
  if (!(tier in MIX_TIERS) || total !== MIX_TIERS[tier]) return read();
  if (slugs.length === 1) return add(slugs[0], tier);   // 1 sabor = kit normal, sem taxa
  const item = { mix: counts, tier, qty: 1 };
  const key = lineKey(item);
  const items = read().items.filter((i) => i.tier !== "sub");
  const line = items.find((i) => lineKey(i) === key);
  if (line) line.qty = Math.min(line.qty + 1, MAX_QTY);
  else if (items.length < MAX_LINES) items.push(item);
  return save({ items });
}
function setQtyByKey(key, qty) {
  const cart = read();
  const line = cart.items.find((i) => lineKey(i) === key);
  if (!line) return cart;
  if (qty <= 0) return removeByKey(key);
  line.qty = Math.min(qty, MAX_QTY);
  return save(cart);
}
function removeByKey(key) {
  const cart = read();
  cart.items = cart.items.filter((i) => lineKey(i) !== key);
  return save(cart);
}
/* legado (assinatura por flavor/tier) — mantido pros módulos antigos */
function setQty(flavor, tier, qty) { return setQtyByKey(`${flavor}:${tier}`, qty); }
function removeLine(flavor, tier) { return removeByKey(`${flavor}:${tier}`); }
function clearCart() { return save({ items: [] }); }

function activeLines(cart = read()) { return cart.items.filter((i) => !i.done); }
function countKits(cart = read()) { return activeLines(cart).reduce((s, i) => s + i.qty, 0); }
function subtotalCents(cart = read()) {
  return activeLines(cart).reduce((s, i) => s + i.qty * unitCents(i), 0);
}
function isSubOnly(cart = read()) {
  const a = activeLines(cart);
  return a.length === 1 && a[0].tier === "sub";
}
function fmtBRL(cents) {
  return (cents / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}
function onCart(fn) { window.addEventListener("hyu:cart", (e) => fn(e.detail)); }
function onCartOpen(fn) { window.addEventListener("hyu:cart:open", fn); }

/* UTMs (hyuutm1): guardadas na 1ª página com UTM (localStorage hyu-utm, 30 dias)
 * pra não sumirem quando o cliente navega pelo site. Vão no metadata da sessão
 * E coladas na URL do checkout Paggins (integração nativa Paggins → UTMify). */
const TRACK_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid", "ref", "src"];
const LS_UTM = "hyu-utm";
const UTM_TTL = 30 * 24 * 3600 * 1000;
function trackParams() {
  const q = new URLSearchParams(location.search), now = {};
  for (const k of TRACK_KEYS) {
    const v = q.get(k);
    if (v) now[k] = v;
  }
  try {
    // last-touch: campanha nova na URL substitui o conjunto inteiro (não mistura)
    if (Object.keys(now).length) {
      localStorage.setItem(LS_UTM, JSON.stringify({ t: Date.now(), p: now }));
      return now;
    }
    const saved = JSON.parse(localStorage.getItem(LS_UTM) || "null");
    if (saved && saved.p && Date.now() - saved.t < UTM_TTL) return saved.p;
  } catch {}
  return now;
}
trackParams(); // grava já na chegada, antes de qualquer navegação interna
function withTrack(url) {
  const u = new URL(url), p = trackParams();
  for (const k of Object.keys(p)) if (!u.searchParams.has(k)) u.searchParams.set(k, p[k]);
  return u.toString();
}
function meta() {
  const m = { ...trackParams() };
  m.page = location.pathname;
  return m;
}
function directUrl(item) {
  return withTrack(LINKS[item.flavor][item.tier]);
}
function bridgeItems(lines) {
  return lines.filter((i) => i.tier !== "sub").map((i) =>
    i.mix ? { mix: i.mix, tier: i.tier, qty: i.qty }
      : COMBO_SET.has(i.flavor) ? { combo: i.flavor, qty: i.qty }
      : { flavor: i.flavor, tier: i.tier, qty: i.qty });
}
async function checkout(cart = read()) {
  const items = bridgeItems(activeLines(cart));
  if (!items.length) throw new Error("carrinho vazio");
  let r;
  try {
    r = await fetch(`${API}/checkout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items, meta: meta(), origin: location.origin }),
    });
  } catch {
    throw new Error("__RETRY__");
  }
  if (!r.ok) {
    // 400 = problema do carrinho (ex: sabor esgotado) → propaga a msg do bridge
    // ("Hot Lemon esgotado — ...tira da sacola"); 5xx/rede → genérico "tenta de novo".
    let detail = "";
    try { detail = (await r.json())?.detail || ""; } catch {}
    throw new Error(r.status < 500 && detail ? detail : "__RETRY__");
  }
  const d = await r.json();
  if (!d?.checkoutUrl) throw new Error("__RETRY__");
  return withTrack(d.checkoutUrl);
}

export {
  API as C, add as a, onCartOpen as b, checkout as c, subtotalCents as d,
  TIERS as e, fmtBRL as f, read as g, countKits as h, isSubOnly as i,
  COMBOS_META as j, FLAVORS as k, directUrl as l, clearCart as m, onCart as o,
  activeLines as p, removeLine as r, setQty as s,
  addMix as t, lineKey as u, removeByKey as v, setQtyByKey as w,
  MIX_FEE as y, unitCents as z, MIX_STEP as x,
};
