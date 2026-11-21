/* Empty configuration keeps this local page free of third-party requests. */
(() => {
  'use strict';
  function validCheckout(value) {
    if (typeof value !== 'string' || !value.trim()) return null;
    try {
      const url = new URL(value);
      return url.protocol === 'https:' && url.hostname && !url.username && !url.password ? url.href : null;
    } catch { return null; }
  }
  fetch('config.json', {cache: 'no-store'})
    .then(response => { if (!response.ok) throw new Error('Config unavailable'); return response.json(); })
    .then(config => {
      const checkout = validCheckout(config.checkoutUrl);
      const pixel = typeof config.pixelId === 'string' && /^\d+$/.test(config.pixelId) ? config.pixelId : '';
      if (pixel) {
        const fbq = window.fbq = window.fbq || function () {
          fbq.callMethod ? fbq.callMethod.apply(fbq, arguments) : fbq.queue.push(arguments);
        };
        fbq.queue = fbq.queue || [];
        fbq.push = fbq; fbq.loaded = true; fbq.version = '2.0';
        fbq('init', pixel);
        const script = document.createElement('script');
        script.async = true;
        script.onload = () => fbq('track', 'PageView');
        script.src = 'https://connect.facebook.net/en_US/fbevents.js';
        document.head.appendChild(script);
      }
      if (checkout) document.querySelectorAll('[data-buy]').forEach(button => {
        button.addEventListener('click', event => {
          event.preventDefault();
          if (pixel && typeof window.fbq === 'function') window.fbq('track', 'InitiateCheckout');
          window.location.assign(checkout);
        });
      });
    }).catch(() => { /* Native #oferta anchors remain functional. */ });
})();
