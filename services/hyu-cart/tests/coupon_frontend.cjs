// Run with node services/hyu-cart/tests/coupon_frontend.cjs (no browser/network).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname, '../../../ofertas/hyuoficial/coupon.js'), 'utf8');

function visit(pathname = '/', storage = new Map()) {
  let posted, bar, reloaded = false;
  const sandbox = {
    location: { pathname, search: '', hash: '', reload() { reloaded = true; } },
    history: { replaceState() {} },
    localStorage: {
      getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key),
    },
    document: {
      readyState: 'complete', head: { appendChild() {} },
      body: { insertBefore(node) { bar = node; } },
      createElement() {
        const button = { addEventListener(event, callback) { this.click = callback; } };
        return { setAttribute() {}, querySelector() {
          return this.innerHTML.includes('aria-label="Remover cupom"') ? button : null;
        } };
      },
      createTreeWalker() { return { nextNode() { return null; } }; },
    },
    NodeFilter: { SHOW_TEXT: 4 },
    MutationObserver: class { observe() {} },
    window: { fetch(url, init) { posted = JSON.parse(init.body); } },
  };
  vm.runInNewContext(source, sandbox);
  sandbox.window.fetch('https://cart.hyudrinks.com/checkout', {
    method: 'POST', body: JSON.stringify({ items: [{ combo: 'super-kit', qty: 1 }] }),
  });
  return { posted, bar, storage, get reloaded() { return reloaded; } };
}

const clean = visit();
assert.equal(clean.posted.coupon, undefined, 'clean visitor must not receive a coupon');
assert.equal(clean.bar, undefined, 'clean visitor must not see a discount banner');
assert.equal(visit('/', new Map([['hyu_coupon', 'INVALID']])).posted.coupon, undefined);
for (const [code, pct] of [['ARTHURPC', 5], ['COSENZA10', 10], ['JUVZS', 10], ['DOPAMINA10', 10]]) {
  const linked = visit('/' + code.toLowerCase());
  assert.equal(linked.posted.coupon, code, 'explicit link must keep its own coupon');
  assert.ok(linked.bar.innerHTML.includes(pct + '% OFF'));
  assert.equal(visit('/', linked.storage).posted.coupon, code, 'chosen coupon persists');
  const button = linked.bar.querySelector('.x');
  assert.ok(button, code + ' must be removable');
  button.click();
  assert.ok(linked.reloaded);
  assert.equal(visit('/', linked.storage).posted.coupon, undefined, 'removed coupon stays absent');
}
assert.equal(visit('/ARTHURPC', new Map([['hyu_coupon', 'COSENZA10']])).posted.coupon, 'ARTHURPC');
console.log('PASS: clean/invalid sessions, explicit coupons, 5% priority, persistence and removal');
