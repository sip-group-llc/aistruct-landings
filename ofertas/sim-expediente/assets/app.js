/* No network outside the local site until a valid pixel is explicitly configured. */
(() => {
  'use strict';
  const buttons = [...document.querySelectorAll('[data-buy]')];
  const fallback = () => buttons.forEach(button => button.setAttribute('href', '#oferta'));
  fallback();
  let checkout = null;
  let pixelEnabled = false;
  const validCheckout = value => {
    if (typeof value !== 'string' || !value.trim()) return null;
    try {
      const url = new URL(value); // Requires an absolute URL; rejects javascript/data.
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
      if (url.protocol === 'http:' && !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) return null;
      return url.href;
    } catch { return null; }
  };
  const enablePixel = id => {
    if (typeof id !== 'string' || !/^\d{5,25}$/.test(id)) return;
    const fbq = function () { fbq.callMethod ? fbq.callMethod.apply(fbq, arguments) : fbq.queue.push(arguments); };
    fbq.push = fbq; fbq.loaded = true; fbq.version = '2.0'; fbq.queue = [];
    window.fbq = fbq;
    const script = document.createElement('script');
    script.async = true;
    script.src = 'https://connect.facebook.net/en_US/fbevents.js';
    document.head.appendChild(script);
    fbq('init', id);
    fbq('track', 'PageView');
    pixelEnabled = true;
  };
  buttons.forEach(button => button.addEventListener('click', event => {
    if (!checkout) return;
    // A real activation of a real destination is required. Scripted dispatch is ignored.
    if (event.isTrusted && pixelEnabled && typeof window.fbq === 'function') {
      window.fbq('track', 'InitiateCheckout');
    }
  }));
  fetch('config.json', {cache: 'no-store'})
    .then(response => { if (!response.ok) throw new Error('config'); return response.json(); })
    .then(config => {
      checkout = validCheckout(config.checkoutUrl);
      if (checkout) buttons.forEach(button => button.setAttribute('href', checkout));
      enablePixel(config.pixelId);
    })
    .catch(() => { checkout = null; fallback(); });
})();
