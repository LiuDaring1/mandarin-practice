/* Additional acceptance: short screens, failures, and word-count reward tiers. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = 'http://127.0.0.1:8771';
const out = path.resolve(__dirname, '../handoff/ui-refresh-2026-09-12');
const results = [];
let browser, page;
async function shot(name) { await page.waitForTimeout(350); await page.screenshot({ path: `${out}/screenshots/${name}.png`, fullPage: true }); }
(async () => {
  assert((await (await fetch(base + '/__qa/info')).json()).isolated);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.route('**/api/home', r => r.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"test"}' }));
  await page.goto(base);
  await page.waitForSelector('#home-retry-btn');
  await shot('home-error-390');
  assert((await page.locator('#home-retry-btn').boundingBox()).y < 740);
  await page.unroute('**/api/home');
  await page.locator('#home-retry-btn').click();
  await page.waitForFunction(() => !els.startBtn.disabled && els.readyHint.hidden);
  results.push('首页加载失败可见、重试成功，无重复绑定');
  await shot('home-words-390');
  const rects = await page.evaluate(() => ({ button: els.startBtn.getBoundingClientRect().bottom, nav: document.querySelector('.tab-bar').getBoundingClientRect().top }));
  assert(rects.button + 8 <= rects.nav);
  for (const size of [{ width: 360, height: 640 }, { width: 390, height: 667 }, { width: 430, height: 740 }]) {
    await page.setViewportSize(size);
    await page.locator('#start-btn').scrollIntoViewIfNeeded();
    await page.evaluate(() => scrollTo(0, document.documentElement.scrollHeight));
    assert(await page.evaluate(() => document.documentElement.scrollWidth === innerWidth && els.startBtn.getBoundingClientRect().bottom <= document.querySelector('.tab-bar').getBoundingClientRect().top));
    await shot(`home-short-${size.width}x${size.height}`);
  }
  results.push('360×640、390×667、430×740 短屏自然滚动，按钮不遮挡');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => scrollTo(0, 0));
  for (let index = 0; index < 3; index++) {
    await page.locator('#entry-list .entry-btn').nth(index).click();
    await page.locator('.filter-chip').first().click();
    await page.locator('#filter-all').click();
    assert(await page.evaluate(() => state.filterDraft.length === allFinalsOf(currentEntry()).length));
    await shot(`filter-tone-${index}`);
    await page.locator('#filter-done').click();
  }
  results.push('三类音筛选、取消单音、恢复全选');
  await page.locator('#tab-sentence').click();
  await page.route('**/api/sentence/session', r => r.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"test"}' }));
  await page.locator('#sentence-start-btn').click();
  await page.waitForFunction(() => state.sentenceMode === 'error');
  await shot('sentence-error-390');
  await page.locator('#sentence-exit-btn').click();
  assert(await page.locator('#view-home').isVisible());
  await page.unroute('**/api/sentence/session');
  await page.locator('#tab-discrim').click();
  await page.route('**/api/discrim/library/session', r => r.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"test"}' }));
  await page.locator('#discrim-start-btn').click();
  await page.waitForFunction(() => state.discrimMode === 'error');
  await shot('discrim-error-390');
  await page.locator('#discrim-exit-btn').click();
  assert(await page.locator('#view-home').isVisible());
  await page.unroute('**/api/discrim/library/session');
  results.push('句子和辨音出题异常仍可退出，页面无死路');

  const rewards = [];
  for (const c of [{ tier: 100, done: 100, expected: 600 }, { tier: 150, done: 150, expected: 900 }, { tier: 100, done: 20, expected: 120 }, { tier: 100, done: 19, expected: 0 }]) {
    await page.evaluate(t => { state.discrimPracticeSize = t; renderDiscrimSizes(); }, c.tier);
    await page.locator('#discrim-start-btn').click();
    await page.waitForFunction(() => state.discrimMode === 'answering');
    // Fixture completed word counts; deliberately use a different syllable count.
    const result = await page.evaluate(async ({ done, tier }) => {
      state.discrimLibraryCompleted = done;
      state.discrimPointCount = done + 7;
      state.discrimPlannedPoints = tier + 15;
      const reward = await settleLibraryReward(done < tier);
      if (state.discrimTickTimer !== null) throw new Error('Timer did not stop');
      return reward;
    }, c);
    assert.equal(result.total_beads, c.expected);
    assert.equal(result.tier_key, c.tier);
    rewards.push({ ...c, actual: result.total_beads });
    await page.evaluate(() => resetToHome());
  }
  results.push({ name: '100／150 词档位、20% 边界及计时停止', rewards });
  await page.locator('#cal-link').click();
  assert.equal(await page.locator('video[poster]').count(), 6);
  for (const p of await page.locator('video').evaluateAll(vs => vs.map(v => v.poster))) assert((await page.request.get(p)).ok());
  await shot('standard-sounds-390');
  await page.locator('#cal-back').click();
  await page.evaluate(() => openPicker('next'));
  await shot('artwork-picker-390');
  const horizontal = await page.locator('.picker-sheet').evaluate(e => e.scrollWidth > e.clientWidth);
  assert(!horizontal);
  await page.keyboard.press('Escape');
  results.push('六个标准音本地封面加载，作品选择弹层无横向溢出');
  console.log('PASS', JSON.stringify(results));
  fs.writeFileSync(`${out}/qa-edges.json`, JSON.stringify(results, null, 2));
})().catch(async e => { console.error(e); process.exitCode = 1; if (page) await shot('edge-failure').catch(()=>{}); }).finally(async () => { if(browser) await browser.close(); });
