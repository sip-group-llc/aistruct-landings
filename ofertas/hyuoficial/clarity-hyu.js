/* HYU — marcações do Microsoft Clarity (projeto yp55htqmdp).
 *
 * O snippet oficial do Clarity fica no <head> de cada página. Este arquivo só
 * adiciona os marcadores do funil (o checkout em si roda em paggins.com, onde
 * não temos script — ver README da integração):
 *
 *  - identify(email): cliente que já informou o e-mail (janela antes do checkout,
 *    salvo em localStorage "hyu-mail") tem a gravação associada ao e-mail.
 *  - evento "checkout_iniciado" + tag paggins_session: quando o site cria a
 *    sessão Paggins (resposta do POST /checkout).
 *  - evento "compra_concluida" + tags na página /obrigado (a Paggins só
 *    redireciona pra lá depois do pagamento).
 */
(function () {
  "use strict";
  var LS_MAIL = "hyu-mail";
  var EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/;

  function cl() {
    try { if (typeof window.clarity === "function") window.clarity.apply(null, arguments); } catch (e) {}
  }
  function identify(mail) {
    mail = String(mail || "").trim().toLowerCase();
    if (!EMAIL_RE.test(mail)) return;
    // custom-id (Clarity faz hash) + friendly-name (aparece legível no painel)
    cl("identify", mail, undefined, undefined, mail);
    cl("set", "cliente_email", mail);
  }

  /* visitante que já deu o e-mail antes (volta ao site, página de obrigado…) */
  try { identify(localStorage.getItem(LS_MAIL)); } catch (e) {}

  /* ── funil: observa o POST /checkout (e-mail enviado + sessão criada) ───── */
  var _fetch = window.fetch;
  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : (input && input.url) || "";
    var isCheckout = /\/checkout(\?|$)/.test(url) && init &&
      String(init.method || "GET").toUpperCase() === "POST";
    if (isCheckout) {
      try {
        var b = JSON.parse(init.body || "{}");
        identify(b && b.customer && b.customer.email);
        if (b && b.coupon) cl("set", "cupom", String(b.coupon));
      } catch (e) {}
    }
    var p = _fetch.apply(this, arguments);
    if (isCheckout) {
      p.then(function (r) {
        if (!r || !r.ok) { cl("event", "checkout_erro"); return; }
        r.clone().json().then(function (d) {
          if (d && d.sessionId) cl("set", "paggins_session", String(d.sessionId));
          if (d && d.totalAmount) cl("set", "valor_centavos", String(d.totalAmount));
          cl("event", "checkout_iniciado");
          cl("upgrade", "checkout_iniciado");   // prioriza a gravação dessa sessão
        }).catch(function () {});
      }).catch(function () { cl("event", "checkout_erro"); });
    }
    return p;
  };

  /* ── página de obrigado: compra concluída ─────────────────────────────── */
  if (/^\/obrigado\/?$/.test(location.pathname)) {
    var q = new URLSearchParams(location.search);
    var sid = q.get("session_id") || "";
    if (q.get("ref")) cl("set", "pedido", q.get("ref"));
    if (/^cs_[A-Za-z0-9]+$/.test(sid)) cl("set", "paggins_session", sid);
    cl("event", "compra_concluida");
    cl("upgrade", "compra_concluida");
  }
})();
