/* Focused retry / stale DOM-event / stalled load checks on the final frontend. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve(__dirname,'../handoff/calibration-mobile-2026-09-12');
const url='http://127.0.0.1:8771', report={checks:[]};
let browser;
(async()=>{
  assert((await(await fetch(url+'/__qa/info')).json()).isolated);
  browser=await chromium.launch({channel:'chrome',headless:true});
  const context=await browser.newContext(),page=await context.newPage();
  await page.goto(url+'/?view=calibration');await page.waitForSelector('.cal-group');
  const click=()=>page.locator('button[data-group="an_ang"][data-seq="ab"]').click();
  const moving=()=>page.waitForFunction(()=>!getCalVideo('an_ang','a').paused&&getCalVideo('an_ang','a').currentTime>.15);
  const idle=()=>page.waitForFunction(()=>els.calStop.disabled);
  await click();await moving();
  await page.evaluate(()=>getCalVideo('an_ang','a').dispatchEvent(new Event('ended')));
  assert.equal(await page.locator('.cal-card.playing video').getAttribute('data-final'),'an');
  await idle();report.checks.push('Premature/stale DOM ended event cannot advance the current queue');

  let deny=true;
  await context.route('**/calibration/an.mp4?**',r=>deny?r.abort('failed'):r.continue());
  await page.evaluate(()=>{const v=getCalVideo('an_ang','a');v.src=calVideoUrl('an')+'&retry-test=1';v.load();});
  await page.waitForFunction(()=>getCalVideo('an_ang','a').error!==null);
  await click();await idle();
  assert.match(await page.locator('#cal-status').innerText(),/失败/);
  deny=false;
  // Retry the exact same button and source; application itself must call load().
  await click();await moving();await idle();
  assert.match(await page.locator('#cal-status').innerText(),/播放完毕/);
  report.checks.push('Real failed network request recovers via same-button retry without changing source or reloading page');

  await page.evaluate(()=>{const v=getCalVideo('an_ang','a');window.qaPlay=v.play;v.play=()=>new Promise(()=>{});});
  await click();await idle();
  assert.match(await page.locator('#cal-status').innerText(),/加载超时/);
  assert(await page.evaluate(()=>[...els.calGroups.querySelectorAll('video')].every(v=>v.paused&&v.onended===null)));
  await page.evaluate(()=>{delete getCalVideo('an_ang','a').play;});
  report.checks.push('12-second loading timeout gives retry feedback and clears queue');
  await page.reload();await page.waitForSelector('.cal-group');
  assert.equal(await page.locator('[data-cal-speed="normal"]').getAttribute('aria-pressed'),'true');
  report.checks.push('Fresh page defaults to normal audible mode');report.status='passed';
})().catch(e=>{report.status='failed';report.failure=e.stack;process.exitCode=1;}).finally(async()=>{
  fs.writeFileSync(path.join(out,'focused-controls-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));if(browser)await browser.close();
});
