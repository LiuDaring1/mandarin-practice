/* Finish the existing UI regression after its eager image-readiness assertion.
   Uses explicit image readiness in its own empty browser context. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve(__dirname,'../handoff/calibration-refresh-2026-09-12'),url='http://127.0.0.1:8771';
(async()=>{
 assert((await(await fetch(url+'/__qa/info')).json()).isolated);
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const report={checks:[],errors:[]};
 try{
  const context=await browser.newContext({viewport:{width:390,height:844}}),page=await context.newPage();
  page.on('pageerror',e=>report.errors.push(e.message));
  await context.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
  await page.goto(url);await page.waitForFunction(()=>!els.startBtn.disabled);
  await page.waitForFunction(()=>state.discrimInfo);
  await page.waitForFunction(()=>[...document.images].every(i=>i.complete&&i.naturalWidth>0));
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await page.locator('#view-home').evaluate(e=>getComputedStyle(e).animationName),'none');
  report.checks.push('Local-only images load; reduced motion is respected');
  await page.route('**/api/sessions',r=>r.fulfill({status:503,contentType:'application/json',body:'{"detail":"QA temporary failure"}'}));
  await page.locator('#start-btn').click();await page.waitForFunction(()=>state.mode==='error');
  await page.screenshot({path:path.join(out,'app-regression/screenshots/audio-error.png'),fullPage:true});
  await page.unroute('**/api/sessions');await page.locator('#replay-btn').click();
  await page.waitForFunction(()=>state.session&&state.mode!=='error');
  await page.locator('#exit-btn').click();await page.locator('#end-btn').click();
  await page.waitForSelector('#complete-home-btn');assert.equal(await page.locator('.reward-amount').count(),0);
  await page.screenshot({path:path.join(out,'app-regression/screenshots/complete-early.png'),fullPage:true});
  report.checks.push('Session generation failure retries successfully; early exit under 20% earns no reward');
  assert.deepEqual(report.errors,[]);report.status='passed';
 }catch(e){report.status='failed';report.failure=e.stack;process.exitCode=1;}
 finally{fs.writeFileSync(path.join(out,'app-regression-tail-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
