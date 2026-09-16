/* Sound integration: full existing UI regression, isolated port 8773, strict gesture playback and event assertions. */
/* Run with the bundled Node + Playwright; start serve_ui_qa.py first.
   Only the server that exposes /__qa/info is accepted. No real user profile. */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'handoff/sound-integration-2026-09-12/full-flow');
const url = 'http://127.0.0.1:8773';
const report = { checks: [], layouts: [], errors: [] };
const mark = (name, detail = true) => { report.checks.push({ name, detail }); console.log('PASS', name); };
const widths = [360, 390, 430, 1024];
let browser, page;

async function shot(name, responsive = false) {
  const sizes = responsive ? widths : [390];
  for (const width of sizes) {
    await page.setViewportSize({ width, height: width === 1024 ? 900 : 844 });
    await page.waitForTimeout(320);
    const layout = await page.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
      innerOverflow: [...document.querySelectorAll('.filter-sheet, .picker-sheet, .detail-sheet')]
        .filter(e => e.clientWidth && e.scrollWidth > e.clientWidth + 1).map(e => e.className),
    }));
    assert(layout.scrollWidth <= layout.width, `${name} overflows at ${width}: ${layout.scrollWidth}`);
    assert.deepEqual(layout.innerOverflow, [], `${name} inner horizontal overflow at ${width}`);
    report.layouts.push({ name, ...layout });
    await page.screenshot({ path: path.join(out, 'screenshots', `${name}-${width}.png`), fullPage: true });
  }
  await page.setViewportSize({ width: 390, height: 844 });
}

async function answerWord(wrong = false) {
  const q = await page.evaluate(() => ({ id: state.discrimSession.session_id, item: currentDiscrimItem() }));
  // The judge is read-only. Ask it for the answer key, then operate actual UI buttons.
  const response = await page.request.post(url + '/api/discrim/answer', { data: {
    session_id: q.id, item_id: q.item.item_id, answers: q.item.points.map(() => 'front'),
  }});
  const key = await response.json();
  for (const r of key.results) {
    const front = wrong ? !r.front : r.front;
    await page.locator(front ? '#discrim-front-btn' : '#discrim-back-btn').click();
  }
  await page.waitForFunction(() => state.discrimMode === 'feedback');
  await page.evaluate(() => clearTimeout(state.discrimFeedbackTimeout));
  await page.waitForTimeout(70); // let the real progress POST complete
}

(async () => {
  assert((await (await fetch(url + '/__qa/info')).json()).isolated);
  fs.mkdirSync(path.join(out, 'screenshots'), { recursive: true });
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  page = await context.newPage();
  page.on('pageerror', e => report.errors.push(e.message));
  await page.goto(url);
  await page.waitForFunction(() => !document.querySelector('#start-btn').disabled);
  await page.waitForFunction(() => state.discrimInfo);
  await page.evaluate(()=>appSfx.ready);
  // Freeze only QA's automatic feedback advance at its source; screenshots and
  // browser automation must not race the real 700ms timer. Answers still use UI/API.
  await page.evaluate(()=>{
    const apply=applyDiscrimFeedback;
    applyDiscrimFeedback=payload=>{apply(payload);clearTimeout(state.discrimFeedbackTimeout);};
  });

  for (const tab of ['words', 'sentence', 'discrim']) {
    await page.locator('#tab-' + tab).click();
    await shot('home-' + tab, true);
  }
  await page.locator('#tab-words').click();
  const firstScreen = await page.evaluate(() => {
    const c = els.startBtn.getBoundingClientRect(), n = document.querySelector('.tab-bar').getBoundingClientRect();
    return { ctaBottom: c.bottom, navTop: n.top, enabled: !els.startBtn.disabled };
  });
  assert(firstScreen.enabled && firstScreen.ctaBottom + 8 <= firstScreen.navTop, JSON.stringify(firstScreen));
  mark('390×844 首页开始按钮完整可见', firstScreen);

  await page.locator('#history-link').click();
  await shot('history-empty');
  await page.locator('#history-empty-start').click();
  await page.locator('#entry-list .entry-btn').first().click();
  await page.waitForFunction(() => document.activeElement.closest('#filter-overlay'));
  await shot('filter', true);
  await page.locator('#filter-done').focus();
  await page.keyboard.press('Tab');
  assert(await page.evaluate(() => document.activeElement.id === 'filter-close'));
  await page.keyboard.press('Escape');
  assert(await page.evaluate(() => !els.app.inert && document.activeElement.closest('#entry-list')));
  mark('弹层焦点循环、Escape 关闭和返回焦点');

  await page.locator('#duration-options button').first().click();
  await page.locator('#start-btn').click();
  await page.waitForFunction(() => els.player.currentTime > .1);
  await page.locator('#pause-btn').click();
  assert(await page.evaluate(() => state.mode === 'paused' && els.player.paused));
  await shot('words-paused', true);
  await page.locator('#pause-btn').click();
  await page.locator('#replay-btn').click();
  await page.waitForFunction(() => state.mode === 'waiting_follow');
  assert((await page.locator('#word-phase').innerText()).includes('跟读计时'));
  await page.locator('#pause-btn').click();
  await shot('words-follow-paused');
  await page.locator('#exit-btn').click();
  await shot('exit-dialog');
  await page.locator('#continue-btn').click();
  mark('字词真实音频、跟读计时、暂停／继续、重播和退出取消');
  // Use the existing debug completion control; compress a five-minute practice for QA.
  await page.evaluate(() => { state.timerRemainingMs = 0; state.completedItems = state.session.item_count; toggleDebug(true); });
  await page.locator('#dbg-finish').click();
  await page.waitForSelector('#complete-body .reward-amount');
  await page.evaluate(() => toggleDebug(false));
  assert.equal(await page.locator('.reward-amount').innerText(), '+600');
  assert((await page.evaluate(()=>appSfx.snapshot().history)).some(e=>e.action==='played'&&e.id==='reward.arrive'));
  await shot('complete-words', true);
  await page.locator('[data-place-art]').click();
  await shot('beads-ready', true);
  const before = await page.evaluate(() => placement.record.placedBeads);
  await page.locator('#detail-place-btn').click();
  assert.equal(await page.evaluate(() => placement.record.placedBeads), before + 1);
  await page.locator('#detail-place-btn').focus();
  await page.keyboard.press('Space');
  assert.equal(await page.evaluate(() => placement.record.placedBeads), before + 2);
  const hold = await page.locator('#detail-place-btn').boundingBox();
  await page.mouse.move(hold.x + hold.width / 2, hold.y + hold.height / 2);
  await page.mouse.down();
  await page.waitForTimeout(850);
  await page.mouse.up();
  assert((await page.evaluate(() => placement.record.placedBeads)) > before + 3);
  await shot('beads-in-progress');
  await page.mouse.down();
  await page.waitForSelector('.iron-stage', { timeout: 12000 });
  await page.mouse.up();
  await shot('beads-ironing');
  await page.waitForSelector('#detail-wall-btn');
  await shot('beads-finished', true);
  assert((await page.evaluate(()=>appSfx.snapshot().history)).some(e=>e.action==='played'&&e.id==='artwork.complete'));
  assert(!/createOscillator/.test(await (await page.request.get(url+'/assets/app.js')).text()));
  await page.locator('#detail-wall-btn').click();
  await shot('artwork-wall', true);
  mark('600 拼点结算；单颗、键盘和真实鼠标长按拼入；熨烫与收藏');

  await page.locator('[data-detail="cat2"]').click();
  await page.locator('#detail-start-btn').click();
  assert.equal(await page.evaluate(() => state.progress.currentArtworkId), 'cat2');
  await shot('beads-cat');
  await page.locator('#detail-close').click();
  await page.evaluate(() => openPicker('next'));
  await shot('artwork-picker', true);
  await page.keyboard.press('Escape');
  await page.locator('#wall-back').click();
  mark('切换猫猫作品，已有拼入和待拼继续保留');

  await page.locator('#tab-sentence').click();
  await page.locator('#sentence-filter-options .entry-btn').last().click();
  await page.locator('#sentence-start-btn').click();
  await page.waitForFunction(() => els.sentencePlayer.currentTime > .1);
  await page.locator('#sentence-pause-btn').click();
  await shot('sentence-practice', true);
  // Render the longest genuine sentence in this generated session at all target widths.
  await page.evaluate(() => renderSentenceItem([...state.sentenceSession.items].sort((a,b)=>b.units.length-a.units.length)[0]));
  await shot('sentence-long', true);
  await page.locator('#sentence-pinyin-toggle').click();
  assert(await page.locator('#sentence-text').evaluate(e => e.classList.contains('no-pinyin')));
  await page.locator('#sentence-replay-btn').click();
  await page.waitForFunction(() => state.sentenceMode === 'following');
  assert((await page.locator('#sentence-phase').innerText()).includes('跟读计时'));
  await page.locator('#sentence-pause-btn').click();
  await page.evaluate(() => { state.sentenceCompleted = 10; state.sentenceElapsedMs = 240000; return finishSentenceSession(false); });
  assert.equal(await page.locator('.reward-amount').innerText(), '+600');
  await shot('complete-sentence', true);
  await page.locator('#sentence-home-btn').click();
  mark('句子真实音频、长句拼音、开关、暂停重播、两遍跟读和结算');

  await page.locator('#tab-discrim').click();
  await page.locator('#discrim-start-btn').click();
  await page.waitForFunction(() => state.discrimMode === 'answering');
  await shot('discrim-practice', true);
  for (let i = 0; i < 50; i++) {
    await answerWord(i < 2);
    if (i === 1) await shot('discrim-wrong');
    await page.evaluate(() => nextDiscrimWord());
  }
  assert.equal(await page.evaluate(() => state.discrimKind), 'warmup');
  await shot('discrim-warmup');
  for (let i = 0; i < 2; i++) { await answerWord(); await page.evaluate(() => nextDiscrimWord()); }
  await page.waitForSelector('#discrim-home-btn');
  assert.equal(await page.locator('.reward-amount').innerText(), '+400');
  assert((await page.evaluate(()=>appSfx.snapshot().history)).some(e=>e.action==='played'&&e.id==='day.complete'));
  assert((await page.evaluate(()=>appSfx.snapshot().history)).some(e=>e.action==='played'&&e.id==='answer.correct'));
  assert((await page.evaluate(()=>appSfx.snapshot().history)).some(e=>e.action==='played'&&e.id==='answer.retry'));
  await shot('complete-discrim', true);
  await page.locator('#discrim-home-btn').click();
  mark('50 词实际答题、连错提示、趁热巩固、300 拼点＋三练 100');

  await page.request.post(url + '/__qa/make-review-due');
  await page.evaluate(() => refreshDiscrimState());
  assert.equal(await page.evaluate(() => discrimInfo().review.due_today), 2);
  await shot('review-due');
  await page.locator('#discrim-review-btn').click();
  await page.waitForFunction(() => state.discrimMode === 'answering');
  await shot('review-practice');
  for (let i = 0; i < 2; i++) { await answerWord(); await page.evaluate(() => nextDiscrimWord()); }
  await page.waitForSelector('#discrim-home-btn');
  assert.equal(await page.locator('.reward-amount').innerText(), '+100');
  await shot('complete-review', true);
  await page.locator('#discrim-home-btn').click();
  mark('独立进度模拟跨天到期复习，两词过关，100 拼点');

  await page.locator('#history-link').click();
  await shot('history', true);
  await page.locator('#history-back').click();
  await page.locator('#cal-link').click();
  await shot('standard-sounds', true);
  assert.equal(await page.locator('.cal-group').count(), 3);
  await page.locator('.cal-seq button').first().click();
  await page.waitForFunction(() => [...document.querySelectorAll('.cal-video video')].some(v => v.currentTime > .1));
  await page.locator('#cal-back').click();
  mark('历史和三个标准音对比组；现有视频真实播放');

  fs.writeFileSync(path.join(out,'sound-history.json'),JSON.stringify(await page.evaluate(()=>appSfx.snapshot()),null,2));
  // Deny external network only: this is a local-server app, so loopback stays reachable.
  await context.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
  await page.reload();
  await page.waitForFunction(() => !els.startBtn.disabled);
  assert(await page.evaluate(() => [...document.images].every(i => i.complete && i.naturalWidth > 0)));
  await page.emulateMedia({ reducedMotion: 'reduce' });
  assert.equal(await page.locator('#view-home').evaluate(e => getComputedStyle(e).animationName), 'none');
  mark('断开外网后刷新仍加载本地素材；减少动态效果');
  await page.route('**/api/sessions', route => route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"QA temporary failure"}' }));
  await page.locator('#start-btn').click();
  await page.waitForFunction(() => state.mode === 'error');
  await shot('audio-error');
  await page.unroute('**/api/sessions');
  await page.locator('#replay-btn').click();
  await page.waitForFunction(() => state.session && state.mode !== 'error');
  await page.locator('#exit-btn').click();
  await page.locator('#end-btn').click();
  await page.waitForSelector('#complete-home-btn');
  assert.equal(await page.locator('.reward-amount').count(), 0);
  await shot('complete-early');
  mark('生成错误可重试；提前退出不足 20% 不奖励');
  assert.deepEqual(report.errors, []);
  mark('无 JavaScript 运行错误');
  fs.writeFileSync(path.join(out, 'qa-results.json'), JSON.stringify(report, null, 2));
  console.log('DONE', report.checks.length, 'checks;', report.layouts.length, 'screenshots');
})().catch(async e => {
  report.failure = e.stack;
  fs.writeFileSync(path.join(out, 'qa-results.json'), JSON.stringify(report, null, 2));
  if (page) await page.screenshot({ path: path.join(out, 'screenshots/failure.png'), fullPage: true }).catch(()=>{});
  console.error(e); process.exitCode = 1;
}).finally(async () => { if (browser) await browser.close(); });
