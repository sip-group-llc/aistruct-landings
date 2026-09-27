/* HYU — pede o e-mail do cliente antes de abrir o checkout Paggins.
 *
 * Intercepta o "Finalizar compra" do drawer (fase de captura, antes do handler
 * nativo), abre uma janelinha pedindo o e-mail e, ao confirmar, deixa o fluxo
 * nativo seguir. O e-mail vai em `customer.email` no POST /checkout: o bridge
 * repassa pra sessão Paggins, que abre já preenchida (em vez do placeholder
 * comprador@hyuoficial.com).
 *
 * - Assinatura pura (link nativo Paggins) não passa por aqui.
 * - E-mail fica salvo em localStorage "hyu-mail" e vem pré-preenchido.
 * - Pede uma vez por carregamento de página.
 */
(function () {
  "use strict";
  var LS_CART = "hyu-cart-v2", LS_MAIL = "hyu-mail";
  var EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/;
  var confirmed = false;

  function hasPaidLines() {
    try {
      var c = JSON.parse(localStorage.getItem(LS_CART) || "");
      return !!(c && Array.isArray(c.items) && c.items.some(function (i) {
        return i && i.tier !== "sub" && i.qty >= 1;
      }));
    } catch (e) { return false; }
  }
  function savedMail() {
    try { return localStorage.getItem(LS_MAIL) || ""; } catch (e) { return ""; }
  }

  /* ── injeta customer.email no POST /checkout (compõe com o patch do coupon.js) ── */
  var _fetch = window.fetch;
  window.fetch = function (input, init) {
    try {
      var url = typeof input === "string" ? input : (input && input.url) || "";
      var m = (init && init.method) || "GET";
      var mail = savedMail();
      if (/\/checkout(\?|$)/.test(url) && String(m).toUpperCase() === "POST" &&
          init && typeof init.body === "string" && EMAIL_RE.test(mail)) {
        var b = JSON.parse(init.body);
        if (b && typeof b === "object") {
          var cust = (b.customer && typeof b.customer === "object") ? b.customer : {};
          if (!cust.email) cust.email = mail;
          b.customer = cust;
          init = Object.assign({}, init, { body: JSON.stringify(b) });
        }
      }
    } catch (e) {}
    return _fetch.call(this, input, init);
  };

  /* ── janela ─────────────────────────────────────────────────────────── */
  var back, form, input, errEl, pendingBtn;
  function build() {
    var st = document.createElement("style");
    st.textContent =
      ".hyumail-back{position:fixed;inset:0;z-index:10000;display:none;align-items:center;justify-content:center;" +
      "padding:16px;background:rgba(0,0,0,.72)}.hyumail-back.open{display:flex}" +
      ".hyumail{width:100%;max-width:420px;background:#0c0c0c;color:#f3efe4;border:2px solid #c4f439;border-radius:14px;" +
      "padding:22px 20px 18px;font-family:'Archivo',system-ui,sans-serif;box-shadow:6px 6px 0 #11150a;position:relative}" +
      ".hyumail h3{margin:0 0 6px;font-family:'Anton',Impact,sans-serif;font-weight:400;font-size:26px;letter-spacing:.3px;line-height:1.05}" +
      ".hyumail p{margin:0 0 14px;font-size:14px;line-height:1.4;opacity:.8}" +
      ".hyumail input{width:100%;box-sizing:border-box;padding:13px 14px;border-radius:10px;border:2px solid #3a3a3a;" +
      "background:#161616;color:#f3efe4;font-size:16px;outline:none}.hyumail input:focus{border-color:#c4f439}" +
      ".hyumail button[type=submit]{margin-top:12px;width:100%;padding:14px;border:0;border-radius:10px;background:#c4f439;" +
      "color:#0c0c0c;font-weight:800;font-size:16px;cursor:pointer}" +
      ".hyumail button[type=submit]:disabled{opacity:.6;cursor:default}" +
      ".hyumail .err{min-height:18px;margin:8px 0 0;font-size:13px;color:#ff8a7a}" +
      ".hyumail .x{position:absolute;top:10px;right:12px;background:none;border:0;color:#f3efe4;opacity:.6;" +
      "font-size:22px;line-height:1;cursor:pointer;padding:4px}.hyumail .x:hover{opacity:1}";
    document.head.appendChild(st);

    back = document.createElement("div");
    back.className = "hyumail-back";
    back.innerHTML =
      '<form class="hyumail" role="dialog" aria-modal="true" aria-labelledby="hyumail-t" novalidate>' +
      '<button class="x" type="button" aria-label="Fechar">&times;</button>' +
      '<h3 id="hyumail-t">Qual o seu e-mail?</h3>' +
      "<p>Enviamos a confirmação e o rastreio do pedido pra ele.</p>" +
      '<input type="email" name="email" autocomplete="email" inputmode="email" placeholder="seu@email.com" required>' +
      '<p class="err" aria-live="polite"></p>' +
      '<button type="submit">Ir para o pagamento →</button>' +
      "</form>";
    document.body.appendChild(back);
    form = back.querySelector("form");
    input = form.querySelector("input");
    errEl = form.querySelector(".err");

    back.addEventListener("click", function (e) {
      if (e.target === back || e.target.closest(".x")) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && back.classList.contains("open")) close();
    });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var v = input.value.trim().toLowerCase();
      if (!EMAIL_RE.test(v)) {
        errEl.textContent = "Confere o e-mail — parece que falta algo.";
        input.focus();
        return;
      }
      try { localStorage.setItem(LS_MAIL, v); } catch (err) {}
      confirmed = true;
      close();
      if (pendingBtn) pendingBtn.click();   // segue o fluxo nativo do drawer
    });
  }
  function open(btn) {
    if (!back) build();
    pendingBtn = btn;
    errEl.textContent = "";
    input.value = savedMail();
    back.classList.add("open");
    setTimeout(function () { input.focus(); input.select(); }, 60);
  }
  function close() { if (back) back.classList.remove("open"); }

  /* bfcache: voltou do checkout → pede de novo (pré-preenchido) */
  window.addEventListener("pageshow", function (e) { if (e.persisted) confirmed = false; });

  document.addEventListener("click", function (e) {
    var btn = e.target && e.target.closest && e.target.closest("[data-cd-checkout]");
    if (!btn || confirmed || !hasPaidLines()) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    e.stopPropagation();
    open(btn);
  }, true);
})();
