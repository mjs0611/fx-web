// Exercise the shipped script through a small DOM double; no browser/network required.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../assets/site.js'), 'utf8');

class Element {
  constructor(tag = 'div', attrs = {}) {
    this.tagName = tag;
    this.attrs = attrs;
    this.dataset = {};
    this.children = [];
    this.listeners = {};
    this.style = {};
    const classes = new Set();
    this.classList = { add: (...names) => names.forEach(name => classes.add(name)), remove: (...names) => names.forEach(name => classes.delete(name)), contains: name => classes.has(name) };
    this.animations = [];
    this.textContent = '';
    this.hidden = true;
    this.disabled = true;
    this.value = '';
  }
  setAttribute(key, value) { this.attrs[key] = value; }
  getAttribute(key) { return this.attrs[key]; }
  removeAttribute(key) { delete this.attrs[key]; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(event, callback) { this.listeners[event] = callback; }
  fire(event) { this.listeners[event]({ target: this }); }
  closest() { return this; }
  querySelectorAll() { return []; }
  animate(frames, options) {
    const animation = { frames, options, canceled: false, cancel() { this.canceled = true; } };
    this.animations.push(animation);
    return animation;
  }
}
function mount({ numerator = '9', denominator = '1', unit = '엔', topic = '은', toward = '으로', points, animated = false, reduced = false, reveals = [], navigation, storage } = {}) {
  const input = new Element('input'); input.value = '100';
  const option = new Element('option'); option.dataset = { numerator, denominator, unit, topic, toward };
  const currency = new Element('select'); currency.options = [option]; currency.selectedIndex = 0;
  const swap = new Element('button'); swap.dataset = { direction: 'to-krw' };
  const label = new Element('span');
  const output = new Element('output');
  const counter = new Element('span');
  const icon = new Element('svg');
  const result = new Element();
  const converter = new Element();
  converter.querySelector = (selector) => ({ '#amount': input, '#currency': currency, '#direction': swap, '#conversion-label': label, '[data-counter]': counter, '.swap-icon': icon, '.result': result, output })[selector];
  const data = new Element('script'); data.textContent = JSON.stringify(points);
  const chart = new Element();
  const summary = new Element();
  const controls = new Element();
  const buttons = [30, 90, 365, 0].map(range => {
    const button = new Element('button'); button.dataset.range = String(range); return button;
  });
  controls.querySelectorAll = () => buttons;
  const document = {
    querySelector: selector => ({ '[data-converter]': converter, '.range-buttons': controls, '.currencies': navigation })[selector],
    querySelectorAll: () => reveals,
    getElementById: id => ({ 'chart-data': points ? data : null, 'trend-chart': chart, 'chart-summary': summary })[id],
    createElement: tag => new Element(tag),
    createElementNS: (_, tag) => new Element(tag),
  };
  const frames = new Map();
  let nextFrame = 0;
  const preference = { matches: reduced, listeners: [], addEventListener: (_, listener) => preference.listeners.push(listener) };
  const environment = { document, Intl, Number, Date, Math, matchMedia: () => preference, sessionStorage: storage };
  const observers = [];
  if (animated) {
    environment.requestAnimationFrame = callback => { frames.set(++nextFrame, callback); return nextFrame; };
    environment.cancelAnimationFrame = id => frames.delete(id);
    environment.IntersectionObserver = class {
      constructor(callback) { this.callback = callback; this.observed = new Set(); observers.push(this); }
      observe(element) { this.observed.add(element); }
      unobserve(element) { this.observed.delete(element); }
      disconnect() { this.observed.clear(); }
    };
  }
  vm.runInNewContext(source, environment);
  const advance = now => { const pending = [...frames.values()]; frames.clear(); pending.forEach(callback => callback(now)); };
  return { input, currency, option, swap, label, output, counter, icon, result, controls, buttons, chart, summary, frames, advance, observers, preference };
}
function descendants(root, tag) {
  return root.children.flatMap(child => [...(child.tagName === tag ? [child] : []), ...descendants(child, tag)]);
}

test('JPY input is actual yen, with unrounded per-yen fraction', () => {
  const page = mount({ numerator: '2701', denominator: '300' });
  assert.equal(page.output.textContent, '900.33원');
  assert.equal(page.label.textContent, '100엔은 약');
  assert.equal(page.input.disabled, false);
  assert.equal(page.currency.disabled, false);
  assert.equal(page.swap.hidden, false);
  page.input.value = '1'; page.input.fire('input');
  assert.equal(page.output.textContent, '9.00원');
  page.swap.listeners.click();
  assert.equal(page.output.textContent, '0.11엔');
  assert.equal(page.label.textContent, '1원은 약');
  assert.equal(page.swap.textContent, '엔을 원화로 바꾸기');
});
test('large KRW results show whole won; default USD 100 reads like the mockup', () => {
  const page = mount({ numerator: '132949', denominator: '100', unit: '달러', topic: '는', toward: '로' });
  assert.equal(page.output.textContent, '132,949원');
  assert.equal(page.label.textContent, '100달러는 약');
  assert.equal(page.swap.textContent, '원화를 달러로 바꾸기');
});
test('currency select switches the rate and unit', () => {
  const page = mount({ numerator: '1400', unit: '달러', topic: '는', toward: '로' });
  const gbp = { dataset: { numerator: '1800', denominator: '1', unit: '파운드', topic: '는' } };
  page.currency.options.push(gbp); page.currency.selectedIndex = 1; page.currency.fire('change');
  assert.equal(page.output.textContent, '180,000원');
  assert.equal(page.label.textContent, '100파운드는 약');
});
test('converter updates direction, accepts zero, rejects empty/negative/nonfinite/too-large amounts', () => {
  const page = mount({ numerator: '1400', unit: '달러', topic: '는', toward: '로' });
  page.input.value = '2800'; page.swap.listeners.click();
  assert.equal(page.output.textContent, '2.00달러');
  for (const bad of ['', ' ', '-1', 'Infinity', 'NaN', '1000000000001']) {
    page.input.value = bad; page.input.fire('input');
    assert.equal(page.input.attrs['aria-invalid'], 'true');
    assert.equal(page.output.textContent, '0부터 1조까지 금액을 입력해 주세요.');
  }
  page.input.value = '0'; page.input.fire('input');
  assert.equal(page.output.textContent, '0.00달러');
  assert.equal(page.input.attrs['aria-invalid'], undefined);
});
test('range selection keeps only observations and never bridges weekends or holidays', () => {
  const points = [['2025-09-01', 800], ['2026-08-03', 810], ['2026-09-04', 900], ['2026-09-07', 910], ['2026-09-08', 905], ['2026-09-10', 920]];
  const page = mount({ points });
  assert.equal(page.controls.hidden, false);
  page.controls.listeners.click({ target: page.buttons[0] });
  assert.equal(descendants(page.chart, 'circle').length, 4);
  assert.equal(descendants(page.chart, 'line').length, 1);
  assert.equal(page.buttons[0].attrs['aria-pressed'], 'true');
  assert.equal(page.buttons[1].attrs['aria-pressed'], 'false');
  assert.match(page.summary.textContent, /^4개 관측/);
  page.controls.listeners.click({ target: page.buttons[1] });
  assert.equal(descendants(page.chart, 'circle').length, 5);
  page.controls.listeners.click({ target: page.buttons[2] });
  assert.equal(descendants(page.chart, 'circle').length, 5);
  page.controls.listeners.click({ target: page.buttons[3] });
  assert.equal(descendants(page.chart, 'circle').length, 6);
});
test('single or flat observations produce finite chart coordinates', () => {
  for (const points of [[['2026-09-07', 900]], [['2026-09-07', 900], ['2026-09-08', 900]]]) {
    const page = mount({ points });
    page.controls.listeners.click({ target: page.buttons[0] });
    for (const circle of descendants(page.chart, 'circle')) {
      assert.ok(Number.isFinite(Number(circle.attrs.cx)));
      assert.ok(Number.isFinite(Number(circle.attrs.cy)));
    }
  }
});

test('counter exposes final output immediately, retargets from current value and cancels invalid input', () => {
  const page = mount({ numerator: '1400', unit: '달러', topic: '는', animated: true });
  assert.equal(page.output.textContent, '140,000원');
  assert.equal(page.counter.textContent, '0.00원');
  assert.equal(page.output.classList.contains('is-counted'), true);
  page.advance(0); page.advance(300);
  const intermediate = page.counter.textContent;
  assert.notEqual(intermediate, '140,000원');
  page.input.value = '200'; page.input.fire('input');
  assert.equal(page.output.textContent, '280,000원');
  assert.equal(page.counter.textContent, intermediate);
  assert.equal(page.frames.size, 1);
  page.advance(300); page.advance(900);
  assert.equal(page.counter.textContent, '280,000원');
  assert.equal(page.frames.size, 0);
  page.input.value = '300'; page.input.fire('input');
  page.input.value = ''; page.input.fire('input');
  assert.equal(page.frames.size, 0);
  assert.equal(page.counter.textContent, page.output.textContent);
});

test('swap rotates with direction, crosses values and replaces interrupted animations', () => {
  const page = mount({ animated: true });
  page.swap.listeners.click();
  assert.equal(page.icon.style.transform, 'rotate(180deg)');
  assert.equal(page.result.animations[0].options.duration, 260);
  assert.match(page.input.animations[0].frames[0].transform, /18px/);
  page.swap.listeners.click();
  assert.equal(page.icon.style.transform, 'rotate(360deg)');
  assert.equal(page.result.animations[0].canceled, true);
  assert.equal(page.swap.dataset.direction, 'to-krw');
});

test('reveal observes once, staggers 50ms and moves each dot from its own mean', () => {
  const rows = [new Element(), new Element()];
  const dots = rows.map(() => { const dot = new Element(); dot.dataset = { average: '42.50', today: '18.25' }; return dot; });
  rows.forEach((row, index) => { row.querySelectorAll = () => [dots[index]]; });
  const page = mount({ animated: true, reveals: rows });
  assert.ok(rows.every(row => row.classList.contains('reveal-pending')));
  const observer = page.observers[0];
  observer.callback([{ target: rows[0], isIntersecting: false }]);
  assert.equal(observer.observed.size, 2);
  observer.callback(rows.map(target => ({ target, isIntersecting: true })));
  assert.equal(observer.observed.size, 0);
  assert.deepEqual(rows.map(row => row.style.animationDelay), ['0ms', '50ms']);
  assert.equal(dots[1].animations[0].frames[0].transform, 'translateX(42.50%)');
  assert.equal(dots[1].animations[0].frames[1].transform, 'translateX(18.25%)');
  assert.equal(dots[1].animations[0].options.duration, 650);
  rows[0].fire('animationend');
  assert.equal(rows[0].classList.contains('reveal-enter'), false);
});

test('reduced motion shows final numbers and static positions, including mid-animation changes', () => {
  const row = new Element();
  const page = mount({ animated: true, reduced: true, reveals: [row] });
  assert.equal(page.counter.textContent, page.output.textContent);
  assert.equal(page.frames.size, 0);
  assert.equal(row.classList.contains('reveal-pending'), false);
  page.swap.listeners.click();
  assert.equal(page.result.animations.length, 0);
  const moving = mount({ animated: true });
  moving.preference.matches = true;
  moving.preference.listeners.forEach(listener => listener({ matches: true }));
  assert.equal(moving.counter.textContent, moving.output.textContent);
  assert.equal(moving.frames.size, 0);
  moving.input.value = ''; moving.input.fire('input');
  moving.preference.listeners.forEach(listener => listener({ matches: true }));
  assert.equal(moving.counter.textContent, '0부터 1조까지 금액을 입력해 주세요.');
});

test('currency indicator slides across native page links without intercepting navigation', () => {
  const navigation = new Element('nav');
  const links = ['/usd/', '/jpy/', '/eur/', '/cny/', '/gbp/'].map((href, index) => {
    const link = new Element('a', { href });
    link.getBoundingClientRect = () => ({ left: 20 + 70 * index, width: 64 });
    return link;
  });
  const values = new Map([['fx-previous-currency', '/usd/']]);
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
  navigation.querySelectorAll = () => links;
  navigation.querySelector = () => links[3];
  navigation.getBoundingClientRect = () => ({ left: 20 });
  mount({ navigation, storage });
  const indicator = navigation.children[0];
  assert.equal(indicator.style.transform, 'translateX(210px) scaleX(64)');
  assert.equal(indicator.animations[0].frames[0].transform, 'translateX(0px) scaleX(64)');
  assert.equal(indicator.animations[0].options.duration, 300);
  let prevented = false;
  navigation.listeners.click({ target: links[4], button: 0, preventDefault: () => { prevented = true; } });
  assert.equal(prevented, false);
  assert.equal(values.get('fx-previous-currency'), '/cny/');
  assert.equal(indicator.style.transform, 'translateX(280px) scaleX(64)');
  navigation.listeners.click({ target: links[0], button: 0, metaKey: true });
  assert.equal(indicator.style.transform, 'translateX(280px) scaleX(64)');
});
