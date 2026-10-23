// Optional browser proof. Uses an existing Playwright installation; installs nothing.
// FX_PLAYWRIGHT_MODULE and FX_CHROMIUM_EXECUTABLE can point at local QA tools.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { chromium } = require(process.env.FX_PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const root = path.resolve(__dirname, '..');
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'fx-motion-browser-'));
  let browser;
  try {
    // Synthetic observations are confined to the temporary browser preview.
    const build = spawnSync('python3', ['-c', `
from datetime import date, timedelta
from pathlib import Path
import sys
import fx
data = fx.empty_history()
for i in range(365):
    day = date(2025, 1, 1) + timedelta(days=i)
    if day.weekday() < 5:
        data['rates'][day.isoformat()] = {'KRW': str(1450 + i % 100), 'USD': '1.1', 'JPY': '160', 'CNY': '8', 'GBP': '.85'}
fx.build(data, Path(sys.argv[1]))
fx.build(fx.empty_history(), Path(sys.argv[1]) / 'empty-preview')
`, temporary], { cwd: root, encoding: 'utf8' });
    assert.equal(build.status, 0, build.stderr);
    const origin = 'http://fx-preview.test';
    async function serve(route) {
      const url = new URL(route.request().url());
      if (url.origin !== origin) return route.abort();
      const pathname = decodeURIComponent(url.pathname);
      let file = path.resolve(temporary, '.' + pathname);
      if (file !== temporary && !file.startsWith(temporary + path.sep)) return route.fulfill({ status: 403, body: '' });
      if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, 'index.html');
      if (!fs.existsSync(file)) return route.fulfill({ status: 404, body: '' });
      const contentType = ({ '.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml' })[path.extname(file)] || 'application/octet-stream';
      return route.fulfill({ contentType, body: fs.readFileSync(file) });
    }
    browser = await chromium.launch({ headless: true, ...(process.env.FX_CHROMIUM_EXECUTABLE ? { executablePath: process.env.FX_CHROMIUM_EXECUTABLE } : {}) });
    for (const width of [390, 1440]) {
      const context = await browser.newContext({ viewport: { width, height: 1000 }, hasTouch: width === 390 });
      await context.route('**/*', serve);
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      async function layout() {
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `overflow at ${width}px`);
        assert.equal(await page.locator('.signal').evaluateAll(signals => signals.every(signal => {
          const range = signal.querySelector('.signal-range').getBoundingClientRect();
          const text = signal.querySelector('.signal-text').getBoundingClientRect();
          return range.right <= text.left && text.right <= signal.getBoundingClientRect().right + 1;
        })), true, `range/text overlap at ${width}px`);
      }
      await page.goto(origin);
      for (const row of await page.locator('.currency-group').all()) {
        await row.scrollIntoViewIfNeeded();
        await page.waitForTimeout(750);
      }
      await layout();
      await page.locator('#amount').fill('1000000000000');
      await page.waitForTimeout(700);
      await layout();
      await page.locator('#direction').click();
      await page.waitForTimeout(700);
      assert.equal(await page.locator('[data-counter]').textContent(), await page.locator('output').textContent());
      await page.emulateMedia({ reducedMotion: 'reduce' });
      await page.locator('#amount').fill('1');
      assert.equal(await page.locator('[data-counter]').textContent(), await page.locator('output').textContent());
      await layout();
      await page.goto(origin + '/jpy/');
      await layout();
      await page.goto(origin + '/empty-preview/');
      await layout();
      assert.deepEqual(errors, []);
      await context.close();
      const staticContext = await browser.newContext({ javaScriptEnabled: false, viewport: { width, height: 1000 } });
      await staticContext.route('**/*', serve);
      const staticPage = await staticContext.newPage();
      await staticPage.goto(origin);
      assert.equal(await staticPage.locator('.signal-range').count(), 5);
      assert.equal(await staticPage.locator('output').isVisible(), true);
      assert.equal(await staticPage.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await staticContext.close();
      console.log(`${width}px: range, huge amount, swap, reduced motion, JPY, empty and JS-off passed`);
    }
  } finally {
    if (browser) await browser.close();
    fs.rmSync(temporary, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
