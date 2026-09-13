/* HYU — Cupom de influencer por link
 * Abrir hyudrinks.com/ARTHURPC (ou /THIAGO /ISA /NATHAN /DIGAO /KAKAU /BVELOSO,
 * /THIAGOC, /COSENZA10 ou /RD10) aplica o desconto
 * em TODO o site: banner no topo + preços riscados + total do carrinho descontado.
 * O desconto REAL é aplicado no bridge (hyu-cart) no unitAmount — aqui só refletimos
 * visualmente e injetamos o `coupon` no POST /checkout. Validação final = bridge.
 *
 * % por cupom (espelha INFLUENCER_COUPONS do bridge). Manter os dois em sincronia.
 */
(function () {
  "use strict";
  // Cupons de influencer. Os cinco originais seguem em 5%; os demais usam 10%.
  var COUPONS = { ARTHURPC: 5, THIAGO: 5, ISA: 5, NATHAN: 5, DIGAO: 5,
                  KAKAU: 10, BVELOSO: 10, THIAGOC: 10,
                  COSENZA10: 10, RD10: 10 };
  var KEY = "hyu_coupon";
  var PRICE_SRC = "R\\$\\s?\\d{1,3}(?:\\.\\d{3})*,\\d{2}";

  /* ---- resolve o cupom: 1) path /CODE  2) localStorage ---- */
  function fromPath() {
    var segs = location.pathname.split("/").filter(Boolean);
    if (segs.length === 1) {
      var c = decodeURIComponent(segs[0]).toUpperCase();
      if (COUPONS[c]) return c;
    }
    return null;
  }
  var code = fromPath();
  if (code) {
    try { localStorage.setItem(KEY, code); } catch (e) {}
    // limpa a URL p/ "/" preservando query/hash, sem recarregar
    try { history.replaceState(null, "", "/" + location.search + location.hash); } catch (e) {}
  } else {
    try { code = localStorage.getItem(KEY); } catch (e) {}
    if (code && !COUPONS[code]) code = null; // cupom obsoleto
  }
  if (!code) return;
  var PCT = COUPONS[code];

  /* ---- helpers de preço ---- */
  function parseBRL(s) {
    return parseFloat(s.replace(/[^\d,]/g, "").replace(/\./g, "").replace(",", "."));
  }
  function fmtBRL(n) {
    return "R$ " + n.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function discount(v) { return Math.round(v * (100 - PCT)) / 100; }

  /* ---- decora preços via text-node (riscado + novo) ----
   * Escopo: text nodes dentro dos containers SEL. Pula preço já decorado
   * (texto dentro de .hyucpn-px) → idempotente e re-render-safe: quando o
   * carrinho reescreve o total/linha, o .hyucpn-px some e o novo texto é
   * redecorado. Não precisa de flag (que travaria totais que mudam). */
  function decorateText(root) {
    var rx = new RegExp(PRICE_SRC, "g");
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) {
        if (!n.nodeValue || n.nodeValue.indexOf("R$") === -1) return NodeFilter.FILTER_REJECT;
        var p = n.parentNode;
        if (!p || (p.closest && (p.closest(".hyucpn-px") || p.closest(".hyucpn-bar")))) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    var todo = [], n;
    while ((n = walker.nextNode())) todo.push(n);
    todo.forEach(function (tn) {
      var s = tn.nodeValue, frag = document.createDocumentFragment(), last = 0, touched = false, m;
      rx.lastIndex = 0;
      while ((m = rx.exec(s))) {
        var v = parseBRL(m[0]);
        frag.appendChild(document.createTextNode(s.slice(last, m.index)));
        if (v > 0) {                            // pula R$ 0,00 (frete/imposto)
          var span = document.createElement("span");
          // selo -X% só nos preços "cheios" (>=30): subtextos /lata ficam limpos
          var badge = v >= 30 ? '<i class="hyucpn-off">−' + PCT + "%</i>" : "";
          span.className = "hyucpn-px" + (v >= 30 ? " hyucpn-px--lg" : "");
          span.innerHTML = '<span class="hyucpn-old">' + m[0] + "</span>" +
            '<b class="hyucpn-new">' + fmtBRL(discount(v)) + "</b>" + badge;
          frag.appendChild(span);
          touched = true;
        } else {
          frag.appendChild(document.createTextNode(m[0]));
        }
        last = m.index + m[0].length;
      }
      if (touched) {
        frag.appendChild(document.createTextNode(s.slice(last)));
        tn.parentNode.replaceChild(frag, tn);
      }
    });
  }
  function scan() {
    // varre o BODY inteiro: todo preço "R$ x,xx" do site (planos, combos, drawer,
    // sticky, hero) é decorado. Os guards do acceptNode garantem idempotência
    // (pula .hyucpn-px/.hyucpn-bar) e re-render-safety do carrinho.
    decorateText(document.body);
  }

  /* ---- intercepta o POST /checkout p/ mandar o cupom pro bridge ---- */
  var _fetch = window.fetch;
  window.fetch = function (input, init) {
    try {
      var url = typeof input === "string" ? input : (input && input.url) || "";
      var m = (init && init.method) || (input && input.method) || "GET";
      if (/\/checkout(\?|$)/.test(url) && String(m).toUpperCase() === "POST" && init && typeof init.body === "string") {
        var b = JSON.parse(init.body);
        if (b && typeof b === "object") {
          b.coupon = code; // bridge valida e grava metadata.coupon p/ atribuição
          init = Object.assign({}, init, { body: JSON.stringify(b) });
        }
      }
    } catch (e) {}
    return _fetch.call(this, input, init);
  };

  /* ---- banner + estilos ---- */
  function injectStyles() {
    var css =
      '.hyucpn-bar{position:relative;z-index:9999;display:flex;align-items:center;justify-content:center;gap:14px;' +
      'flex-wrap:wrap;padding:10px 16px;background:#0c0c0c;color:#f3efe4;border-bottom:3px solid #c4f439;' +
      "font-family:'Archivo',system-ui,sans-serif;line-height:1.15;animation:hyucpnDrop .5s cubic-bezier(.2,.9,.3,1.4) both}" +
      "@keyframes hyucpnDrop{from{transform:translateY(-100%);opacity:0}to{transform:none;opacity:1}}" +
      ".hyucpn-bar .off{font-family:'Anton',Impact,sans-serif;font-size:clamp(20px,4.6vw,30px);color:#c4f439;" +
      "letter-spacing:.3px;line-height:.9;text-shadow:2px 2px 0 #11150a}" +
      ".hyucpn-bar .msg{font-weight:700;font-size:clamp(12px,3.2vw,15px);text-transform:uppercase;letter-spacing:.4px}" +
      ".hyucpn-bar .msg small{display:block;font-weight:500;opacity:.7;letter-spacing:.2px;text-transform:none}" +
      ".hyucpn-bar .chip{display:inline-flex;align-items:center;gap:6px;font-family:'Space Mono',ui-monospace,monospace;" +
      "font-weight:700;font-size:13px;color:#0c0c0c;background:#c4f439;padding:5px 11px;border-radius:999px;" +
      "box-shadow:2px 2px 0 #11150a;white-space:nowrap}" +
      // cor explícita: o site tem b{color:var(--lime)} → sem isso "CUPOM" fica lime no fundo lime
      ".hyucpn-bar .chip b{font-size:11px;color:#0c0c0c}" +
      ".hyucpn-bar .x{position:absolute;right:12px;top:50%;transform:translateY(-50%);background:transparent;border:0;" +
      "color:#f3efe4;opacity:.55;cursor:pointer;font-size:18px;line-height:1;padding:4px}.hyucpn-bar .x:hover{opacity:1}" +
      ".hyucpn-px{display:inline-flex;align-items:baseline;gap:.3em;white-space:nowrap}" +
      ".hyucpn-old{font-size:.7em;font-weight:600;opacity:.5;text-decoration:line-through;" +
      "text-decoration-thickness:.08em;text-underline-offset:0;letter-spacing:-.01em}" +
      ".hyucpn-new{color:inherit;font-weight:inherit;font-variant-numeric:tabular-nums}" +
      ".hyucpn-off{display:inline-block;font-style:normal;font-family:'Space Mono',ui-monospace,monospace;" +
      "font-size:.5em;font-weight:700;line-height:1;letter-spacing:.2px;color:#0c0c0c;background:#c4f439;" +
      "padding:.36em .5em;border-radius:.5em;box-shadow:1.5px 1.5px 0 #11150a;transform:translateY(-.22em)}" +
      // contextos compactos (sticky / total do drawer): só riscado + novo, sem pílula
      "[data-sb-txt] .hyucpn-old,[data-cd-total] .hyucpn-old{font-size:.5em}" +
      "[data-sb-txt] .hyucpn-off,[data-cd-total] .hyucpn-off{display:none}" +
      "@media(max-width:520px){.hyucpn-bar{gap:9px;padding:9px 34px 9px 12px}.hyucpn-bar .msg small{display:none}}";
    var st = document.createElement("style");
    st.id = "hyucpn-style";
    st.textContent = css;
    document.head.appendChild(st);
  }
  function buildBar() {
    var bar = document.createElement("div");
    bar.className = "hyucpn-bar";
    bar.setAttribute("role", "status");
    bar.innerHTML =
      '<span class="off">' + PCT + "% OFF</span>" +
      '<span class="msg">em todo o site<small>desconto aplicado automaticamente no checkout</small></span>' +
      '<span class="chip">🎟️ <b>CUPOM</b>&nbsp;' + code + "</span>" +
      '<button class="x" type="button" aria-label="Remover cupom">✕</button>';
    bar.querySelector(".x").addEventListener("click", function () {
      try { localStorage.removeItem(KEY); } catch (e) {}
      location.reload();
    });
    document.body.insertBefore(bar, document.body.firstChild);
  }

  function init() {
    injectStyles();
    buildBar();
    scan();
    // re-decora quando o carrinho/sticky renderizam (drawer abre, qty muda…)
    var pending = false;
    var mo = new MutationObserver(function () {
      if (pending) return;
      pending = true;
      requestAnimationFrame(function () { pending = false; scan(); });
    });
    mo.observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
