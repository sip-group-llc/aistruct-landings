/* HYU drawer v4.4 (hyumix11: Hot Lemon reativado) — base v4.3 (hyumix10) — checkout HÍBRIDO: kit fixo=link nativo Paggins; MIX (monte seu kit)=bridge (preço dinâmico). Mix builder RESTAURADO. Base: hyumix5.
 * Mudança de UX (pedido do cliente 08/07): "Montar por sabor" virou MONTADOR
 * LATA A LATA — tocar num sabor adiciona 1 LATA (antes adicionava um kit inteiro
 * por clique, que confundia). Misturou sabores = kit personalizado (+taxa).
 * 1 sabor só = kit normal de sempre, sem taxa. Linhas do carrinho agora são
 * endereçadas por lineKey (suporta mix). /_astro/ é immutable — arquivo NOVO.
 */
import {
  a as add, r as removeLine, g as read, p as activeLines, i as isSubOnly,
  l as directUrl, c as checkout, o as onCart, b as onCartOpen, d as subtotal,
  e as TIERS, f as fmt, t as addMix, u as lineKey, v as removeByKey,
  w as setQtyByKey, y as MIX_FEE, z as unitCents, x as MIX_STEP,
} from "./cart.hyumix6.js";

const drawer = document.querySelector("[data-cart-drawer]");
const back = document.querySelector("[data-cart-back]");
const linesEl = drawer?.querySelector("[data-cd-lines]");
const emptyEl = drawer?.querySelector("[data-cd-empty]");
const footEl = drawer?.querySelector("[data-cd-foot]");
const totalEl = drawer?.querySelector("[data-cd-total]");
const ctaEl = drawer?.querySelector("[data-cd-checkout]");
const sizeBtns = Array.from(drawer?.querySelectorAll("[data-cd-size]") ?? []);
const subPick = drawer?.querySelector("[data-cd-subpick]");
const normalPick = drawer?.querySelector("[data-cd-normalpick]");
const subBtns = Array.from(drawer?.querySelectorAll("[data-cd-sub]") ?? []);
const THUMBS = JSON.parse(drawer?.dataset.kitThumbs || "{}");
const FLAVOR_META = JSON.parse(drawer?.dataset.flavorMeta || "{}");
const COMBO_META = JSON.parse(drawer?.dataset.comboMeta || "{}");

const SOON = new Set([]);              // sem estoque — manter = bridge OUT_OF_STOCK_FLAVORS
// 28/07: Pessego com Morango VOLTOU (estoque confirmado pelo gestor). Saiu daqui,
// do SOON_SUBS e do OUT_OF_STOCK_FLAVORS no env do hyu-cart — as tres frentes.
const SOON_SUBS = new Set([]);  // Hot Lemon reativado 29/09/2026
let size = "kit6";
let bumpKey = null;

const esc = (t) => String(t).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const money = (cents, tier) => fmt(cents) + (tier === "sub" ? "/mês" : "");

/* ── linhas da sacola ──────────────────────────────────────────────────── */
function mixCompText(mix) {
  return Object.keys(mix).sort((a, b) => mix[b] - mix[a] || a.localeCompare(b))
    .map((s) => `${mix[s]}× ${FLAVOR_META[s]?.name || s}`).join(" · ");
}
function lineTitle(it) {
  if (it.mix) return `${TIERS[it.tier].label} Personalizado`;
  const combo = COMBO_META[it.flavor];
  return combo ? combo.title : `${TIERS[it.tier].label} · ${FLAVOR_META[it.flavor]?.name || it.flavor}`;
}
function lineSub(it) {
  if (it.mix) return mixCompText(it.mix);
  const combo = COMBO_META[it.flavor];
  return combo ? combo.sub : `${TIERS[it.tier].cans} latas de 269ml`;
}
function lineHtml(it) {
  const key = lineKey(it);
  const combo = it.mix ? null : COMBO_META[it.flavor];
  const color = it.mix ? "#c4f439" : combo?.color || FLAVOR_META[it.flavor]?.color || "#A8CC30";
  const thumb = THUMBS[it.mix ? "super-kit" : it.flavor] || "";
  const qtyHtml = it.tier === "sub" ? "" : `
          <div class="ci__qty">
            <button type="button" data-cd-dec aria-label="Diminuir">−</button>
            <span aria-live="polite">${it.qty}</span>
            <button type="button" data-cd-inc aria-label="Aumentar">+</button>
          </div>`;
  return `
      <li class="ci${bumpKey === key ? " is-bump" : ""}" data-line="${esc(key)}">
        <div class="ci__pic" style="background:${esc(color)}"><img src="${esc(thumb)}" alt="" loading="lazy"></div>
        <div class="ci__info">
          <b>${esc(lineTitle(it))}</b>
          <span>${esc(lineSub(it))}</span>${qtyHtml}
        </div>
        <div class="ci__right">
          <b>${esc(money(it.qty * unitCents(it), it.tier))}</b>
          <button type="button" class="ci__rm" data-cd-rm>remover</button>
        </div>
      </li>`;
}
function render(cart) {
  const items = cart.items;
  if (linesEl) linesEl.innerHTML = items.map(lineHtml).join("");
  bumpKey = null;
  if (emptyEl) emptyEl.hidden = items.length > 0;
  const subOnly = isSubOnly(cart);
  if (totalEl) totalEl.textContent = money(subtotal(cart), subOnly ? "sub" : void 0);
  if (footEl) footEl.hidden = items.length === 0;
  if (ctaEl) ctaEl.href = subOnly ? directUrl(items[0]) : "#";
  if (subPick) subPick.hidden = !subOnly;
  if (normalPick) normalPick.hidden = subOnly;
  subBtns.forEach((b) => {
    const on = subOnly && b.dataset.cdSub === items[0]?.flavor;
    b.classList.toggle("is-active", on);
    b.setAttribute("aria-checked", String(on));
  });
}

/* ── montador lata a lata ─────────────────────────────────────────────── */
const flavBtns = Array.from(drawer?.querySelectorAll("[data-cd-add]") ?? []);
const mixBar = drawer?.querySelector("[data-mix-bar]");
const mixCount = drawer?.querySelector("[data-mix-count]");
const mixFeeEl = drawer?.querySelector("[data-mix-fee]");
const mixPrice = drawer?.querySelector("[data-mix-price]");
const mixAdd = drawer?.querySelector("[data-mix-add]");
const mixClear = drawer?.querySelector("[data-mix-clear]");
let sel = {};

flavBtns.forEach((b) => {
  const badge = document.createElement("span");
  badge.className = "dflav__n";
  badge.hidden = true;
  b.appendChild(badge);
  const minus = document.createElement("span");
  minus.className = "dflav__minus";
  minus.setAttribute("data-mix-dec", "");
  minus.setAttribute("role", "button");
  minus.setAttribute("aria-label", "Tirar 1 lata");
  minus.textContent = "−";
  minus.hidden = true;
  b.appendChild(minus);
});

const selTotal = () => Object.values(sel).reduce((s, n) => s + n, 0);
function targetCans() { return TIERS[size].cans; }

function updateBuilder() {
  const total = selTotal(), target = targetCans();
  const flavors = Object.keys(sel).length;
  const mixed = flavors > 1;
  flavBtns.forEach((b) => {
    const n = sel[b.dataset.cdAdd] || 0;
    const badge = b.querySelector(".dflav__n");
    const minus = b.querySelector(".dflav__minus");
    if (badge) { badge.textContent = String(n); badge.hidden = !n; }
    if (minus) minus.hidden = !n;
    b.classList.toggle("is-picked", n > 0);
    b.classList.toggle("is-maxed", total + MIX_STEP > target);
  });
  if (mixCount) {
    mixCount.textContent = `${total}/${target} latas`;
    mixCount.classList.toggle("is-full", total === target);
  }
  if (mixFeeEl) mixFeeEl.hidden = !mixed;
  if (mixPrice) {
    const cents = TIERS[size].cents + (mixed ? MIX_FEE : 0);
    mixPrice.textContent = total ? fmt(cents) : "";
  }
  if (mixAdd) mixAdd.disabled = total !== target;
  if (mixClear) mixClear.hidden = !total;
}
function resetBuilder() { sel = {}; updateBuilder(); }

function setSize(t) {
  const prev = size;
  size = t;
  sizeBtns.forEach((b) => {
    const on = b.dataset.cdSize === t;
    b.classList.toggle("is-active", on);
    b.setAttribute("aria-checked", String(on));
  });
  if (prev !== t && selTotal() > targetCans()) sel = {}; // encolheu e não cabe
  updateBuilder();
}
sizeBtns.forEach((b) => b.addEventListener("click", () => setSize(b.dataset.cdSize || "kit6")));
if (sizeBtns[0]) {
  sizeBtns[0].classList.add("is-active");
  sizeBtns[0].setAttribute("aria-checked", "true");
}

flavBtns.forEach((b) => b.addEventListener("click", (e) => {
  const slug = b.dataset.cdAdd;
  if (SOON.has(slug)) return;
  if (e.target.closest("[data-mix-dec]")) {
    if (sel[slug]) { sel[slug] -= MIX_STEP; if (sel[slug] <= 0) delete sel[slug]; }
    updateBuilder();
    return;
  }
  if (selTotal() + MIX_STEP > targetCans()) {           // kit cheio — pisca o contador
    mixCount?.classList.remove("is-shake");
    void mixCount?.offsetWidth;
    mixCount?.classList.add("is-shake");
    return;
  }
  sel[slug] = (sel[slug] || 0) + MIX_STEP;
  updateBuilder();
}));
mixClear?.addEventListener("click", resetBuilder);
mixAdd?.addEventListener("click", () => {
  if (selTotal() !== targetCans()) return;
  const slugs = Object.keys(sel);
  bumpKey = slugs.length === 1 ? `${slugs[0]}:${size}` : lineKey({ mix: sel, tier: size });
  addMix({ ...sel }, size);
  resetBuilder();
});

/* ── combos / assinaturas ─────────────────────────────────────────────── */
drawer?.querySelectorAll("[data-cd-combo]").forEach((b) => b.addEventListener("click", () => {
  const slug = b.dataset.cdCombo;
  const tier = COMBO_META[slug]?.tier || "kit6";
  bumpKey = `${slug}:${tier}`;
  add(slug, tier);
}));
subBtns.forEach((b) => b.addEventListener("click", () => {
  if (SOON_SUBS.has(b.dataset.cdSub)) return;
  bumpKey = `${b.dataset.cdSub}:sub`;
  add(b.dataset.cdSub, "sub");
}));

/* ── operações nas linhas ─────────────────────────────────────────────── */
linesEl?.addEventListener("click", (e) => {
  const t = e.target;
  const li = t.closest("[data-line]");
  if (!li) return;
  const key = li.dataset.line || "";
  if (t.closest("[data-cd-rm]")) { removeByKey(key); return; }
  const item = read().items.find((i) => lineKey(i) === key);
  if (!item) return;
  if (t.closest("[data-cd-inc]")) { setQtyByKey(key, item.qty + 1); return; }
  if (t.closest("[data-cd-dec]")) setQtyByKey(key, item.qty - 1);
});

/* ── checkout HÍBRIDO (hyumix6) ────────────────────────────────────────────
   Kit FIXO (combo/sabor) → link NATIVO Paggins (com menu de frete do painel).
   MIX (monte seu kit, preço dinâmico) → BRIDGE (cria sessão Paggins dinâmica). */
let busy = false;
const ctaDefaultText = ctaEl?.textContent || "Finalizar compra →";
// bfcache: ao clicar Finalizar navegamos pro checkout (location.href); se o cliente
// aperta VOLTAR, o navegador restaura a página congelada e o botão fica preso em
// "Processando…"/is-loading (pointer-events:none → não clica). Reseta ao reexibir.
window.addEventListener("pageshow", () => {
  busy = false;
  if (ctaEl) {
    ctaEl.classList.remove("is-loading");
    ctaEl.textContent = ctaDefaultText;
  }
});
ctaEl?.addEventListener("click", async (e) => {
  e.preventDefault();
  if (busy) return;
  const cart = read();
  const items = activeLines(cart);
  if (!items.length) return;
  // assinatura → link fixo (SDK não tem recorrência). TODO O RESTO (kits, combos,
  // mix, multi-item) → BRIDGE: frete correto + nome correto + não perde item.
  // (Antes só o mix ia pro bridge; kit normal ia pro link fixo do 1º item, o que
  //  perdia os outros itens, mostrava nome nativo errado e dava frete grátis.)
  if (isSubOnly(cart)) {
    location.href = directUrl(items[0]);
    return;
  }
  busy = true;
  const old = ctaEl.textContent;
  ctaEl.classList.add("is-loading");
  ctaEl.textContent = "Processando…";
  try {
    location.href = await checkout(cart);
    return;
  } catch (err) {
    ctaEl.classList.remove("is-loading");
    ctaEl.textContent = old || "Finalizar compra →";
    busy = false;
    // msg do bridge (ex: "Hot Lemon esgotado — tira da sacola") vs genérica de rede/5xx
    const m = err && err.message;
    alert(m && m !== "__RETRY__"
      ? m
      : "Não consegui abrir o checkout agora. Tenta de novo em instantes.");
    return;
  }
});

/* ── abre/fecha ───────────────────────────────────────────────────────── */
let lastFocus = null;
function openDrawer() {
  if (!drawer) return;
  render(read());
  updateBuilder();
  if (!drawer.classList.contains("open")) {
    lastFocus = document.activeElement;
    drawer.classList.add("open");
    back?.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    drawer.querySelector(".drawer__x")?.focus();
  }
}
function closeDrawer() {
  if (drawer?.classList.contains("open")) {
    drawer.classList.remove("open");
    back?.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    lastFocus?.focus?.();
  }
}
back?.addEventListener("click", closeDrawer);
drawer?.querySelectorAll("[data-cart-close]").forEach((b) => b.addEventListener("click", closeDrawer));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

document.addEventListener("click", (e) => {
  const opener = e.target.closest("[data-cart-open],[data-buy]");
  if (!opener) return;
  e.preventDefault();
  const buy = opener.getAttribute("data-buy");
  if (buy) {
    const [slug, tierRaw] = buy.split(":");
    if (SOON.has(slug)) { openDrawer(); return; }
    const tier = tierRaw || COMBO_META[slug]?.tier || "kit6";
    bumpKey = `${slug}:${tier}`;
    add(slug, tier);
  } else {
    const openArg = opener.getAttribute("data-cart-open");
    if (openArg === "kit6" || openArg === "kit12") {
      const first = read().items[0];
      if (first?.tier === "sub") removeLine(first.flavor, first.tier);
      setSize(openArg);
    }
  }
  openDrawer();
});

onCart(render);
onCartOpen(openDrawer);
render(read());
updateBuilder();
const qs = new URLSearchParams(location.search);
// ?sacola=1 vem das paginas legais (/termos, /privacidade): la o botao Sacola e
// um link pra ca, porque o drawer (catalogo inteiro) so existe na home.
if (qs.get("checkout") === "cancelado" || qs.get("sacola") === "1") openDrawer();
