(() => {
  'use strict';
  let checkout = '';
  let pixelReady = false;
  const buttons = [...document.querySelectorAll('[data-buy]')];
  const secureCheckout = value => {
    if (typeof value !== 'string' || !value.trim()) return '';
    try {
      const url = new URL(value);
      return url.protocol === 'https:' && url.hostname && !url.username && !url.password ? url.href : '';
    } catch { return ''; }
  };
  buttons.forEach(button => button.addEventListener('click', () => {
    if (checkout && pixelReady && typeof window.fbq === 'function') {
      window.fbq('track', 'InitiateCheckout', { currency: 'BRL', value: 44.90 });
    }
  }));
  fetch('config.json', { credentials: 'same-origin', cache: 'no-store' })
    .then(response => { if (!response.ok) throw new Error('config'); return response.json(); })
    .then(config => {
      checkout = secureCheckout(config.checkoutUrl);
      if (checkout) buttons.forEach(button => { button.href = checkout; });
      const id = typeof config.pixelId === 'string' ? config.pixelId.trim() : '';
      if (!/^\d{5,25}$/.test(id)) return;
      // No Meta resource is requested until an identifier is explicitly configured.
      const fbq = window.fbq = function () {
        fbq.callMethod ? fbq.callMethod.apply(fbq, arguments) : fbq.queue.push(arguments);
      };
      window._fbq = fbq; fbq.push = fbq; fbq.loaded = true; fbq.version = '2.0'; fbq.queue = [];
      const script = document.createElement('script');
      script.async = true;
      script.src = 'https://connect.facebook.net/en_US/fbevents.js';
      script.onload = () => { fbq('init', id); pixelReady = true; fbq('track', 'PageView'); };
      document.head.appendChild(script);
    })
    .catch(() => { /* Original href="#oferta" remains a functional fallback. */ });
})();
