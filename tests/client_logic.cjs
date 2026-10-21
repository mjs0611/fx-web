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
    this.textContent = '';
    this.hidden = true;
    this.disabled = true;
    this.value = '';
  }
  setAttribute(key, value) { this.attrs[key] = value; }
  removeAttribute(key) { delete this.attrs[key]; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(event, callback) { this.listeners[event] = callback; }
  fire(event) { this.listeners[event]({ target: this }); }
  closest() { return this; }
}
function mount({ numerator = '9', denominator = '1', unit = '엔', topic = '은', toward = '으로', points } = {}) {
  const input = new Element('input'); input.value = '100';
  const option = new Element('option'); option.dataset = { numerator, denominator, unit, topic, toward };
  const currency = new Element('select'); currency.options = [option]; currency.selectedIndex = 0;
  const swap = new Element('button'); swap.dataset = { direction: 'to-krw' };
  const label = new Element('span');
  const output = new Element('output');
  const converter = new Element();
  converter.querySelector = (selector) => ({ '#amount': input, '#currency': currency, '#direction': swap, '#conversion-label': label, output })[selector];
  const data = new Element('script'); data.textContent = JSON.stringify(points);
  const chart = new Element();
  const summary = new Element();
  const controls = new Element();
  const buttons = [30, 90, 365, 0].map(range => {
    const button = new Element('button'); button.dataset.range = String(range); return button;
  });
  controls.querySelectorAll = () => buttons;
  const document = {
    querySelector: selector => selector === '[data-converter]' ? converter : controls,
    getElementById: id => ({ 'chart-data': points ? data : null, 'trend-chart': chart, 'chart-summary': summary })[id],
    createElement: tag => new Element(tag),
    createElementNS: (_, tag) => new Element(tag),
  };
  vm.runInNewContext(source, { document, Intl, Number, Date, Math });
  return { input, currency, option, swap, label, output, controls, buttons, chart, summary };
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
