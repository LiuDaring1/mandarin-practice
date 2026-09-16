/* Isolated real Chrome QA. Run serve_ui_qa.py first. Never targets live progress. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'handoff/calibration-mobile-2026-09-12');
const url = 'http://127.0.0.1:8771';
const report = {environment:'Desktop Chrome, isolated context; emulated viewport sizes, not physical phones', checks:[], layouts:[], errors:[]};
let browser, page;
const mark = (name, detail=true) => { report.checks.push({name,detail}); console.log('PASS',name); };
const button = (g,s) => page.locator(`button[data-group="${g}"][data-seq="${s}"]`);
const choose = async (g,s) => {
  await page.locator(`[data-cal-group="${g}"]`).click();
  await button(g,s).click();
};
const idle = () => page.waitForFunction(() => document.querySelector('#cal-stop').disabled);
const moving = () => page.waitForFunction(() => [...document.querySelectorAll('#cal-groups video')].some(v=>!v.paused && v.currentTime>.15));
const allStopped = async () => assert(await page.evaluate(() => [...document.querySelectorAll('#cal-groups video')].every(v=>v.paused && v.onended===null)), 'all players stopped and queues removed');
(async()=>{
  assert.equal((await (await fetch(url+'/__qa/info')).json()).isolated,true);
  fs.mkdirSync(path.join(out,'screenshots'),{recursive:true});
  browser=await chromium.launch({channel:'chrome',headless:true});
  const context=await browser.newContext({viewport:{width:390,height:844}});
  page=await context.newPage();
  page.on('pageerror',e=>report.errors.push(e.message));
  // Local-only loading, including all videos, posters, API and app scripts.
  await context.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
  await page.goto(url+'/?view=calibration');
  await page.waitForSelector('.cal-group');
  assert.equal(await page.locator('.cal-group').count(),3);
  assert.equal(await page.locator('[data-cal-speed="normal"]').getAttribute('aria-pressed'),'true');
  await page.evaluate(()=>{
    window.qaEvents=[]; window.qaPeaks={}; window.qaOverlaps=[];
    window.qaAudio=new AudioContext();
    document.querySelectorAll('#cal-groups video').forEach(v=>{
      const source=qaAudio.createMediaElementSource(v), analyser=qaAudio.createAnalyser();
      source.connect(analyser);analyser.connect(qaAudio.destination);
      const data=new Float32Array(analyser.fftSize);
      setInterval(()=>{
        if(v.paused)return;
        analyser.getFloatTimeDomainData(data);
        const rms=Math.sqrt(data.reduce((a,b)=>a+b*b,0)/data.length);
        qaPeaks[v.dataset.final]=Math.max(qaPeaks[v.dataset.final]||0,rms);
      },20);
      ['playing','ended','error'].forEach(type=>v.addEventListener(type,()=>{
        qaEvents.push({type,final:v.dataset.final,src:v.currentSrc,rate:v.playbackRate,muted:v.muted,time:v.currentTime,audioBytes:v.webkitAudioDecodedByteCount||0});
      }));
    });
    setInterval(()=>{
      const vs=[...document.querySelectorAll('#cal-groups video')].filter(v=>!v.paused && !v.ended);
      if(vs.length>1)qaOverlaps.push(vs.map(v=>v.dataset.final));
    },10);
  });
  for(const mode of ['normal','slow']){
    await page.locator(`[data-cal-speed="${mode}"]`).click();
    for(const group of ['an_ang','en_eng','in_ing']){
      for(const seq of ['a','b','ab','ba']){
        await page.evaluate(()=>{qaEvents=[];qaPeaks={};});
        await choose(group,seq);
        await page.evaluate(()=>qaAudio.resume());
        await moving();
        assert.equal(await button(group,seq).getAttribute('aria-pressed'),'true');
        await idle();
        const result=await page.evaluate(()=>({events:qaEvents,peaks:qaPeaks,status:els.calStatus.textContent}));
        const pair=group.split('_'), expected=seq.split('').map(s=>pair[s==='a'?0:1]);
        assert.deepEqual(result.events.filter(e=>e.type==='ended').map(e=>e.final),expected);
        assert(result.events.filter(e=>e.type==='playing').every(e=>e.rate===(mode==='slow'?.5:1) && e.muted===false));
        assert(result.events.filter(e=>e.type==='ended').every(e=>e.src.includes(`${e.final}.mp4`)));
        for(const final of new Set(expected)){
          assert(result.peaks[final]>.001,`audible PCM expected in both modes: ${final}`);
        }
        assert.match(result.status,/播放完毕/);
        await allStopped();
        mark(`${mode} ${group} ${seq}: natural playback and audio`,result);
      }
    }
  }
  await page.locator('[data-cal-speed="normal"]').click();
  await choose('an_ang','ab'); await moving();
  await page.evaluate(()=>{window.qaOldEnded=getCalVideo('an_ang','a').onended;});
  await choose('in_ing','b'); await moving();
  await page.evaluate(()=>qaOldEnded());
  assert.equal(await page.locator('.cal-card.playing video').getAttribute('data-final'),'ing');
  await idle(); await allStopped();
  mark('rapid group switch ignores captured old ended callback');

  await choose('an_ang','ab'); await moving();
  await page.locator('[data-cal-speed="slow"]').click();
  await page.waitForTimeout(300); await allStopped();
  assert.equal(await page.locator('.cal-seq button.active').count(),0);
  await choose('an_ang','ab'); await moving();
  await page.locator('#cal-stop').click(); await allStopped();
  await page.waitForTimeout(5200); await allStopped();
  mark('speed switch and stop cancel the whole queue');

  await choose('in_ing','b'); await moving();
  await choose('in_ing','b'); await moving();
  assert((await page.locator('video[data-final="ing"]').evaluate(v=>v.currentTime))<1.5);
  await page.locator('#cal-back').click(); await allStopped();
  await page.waitForTimeout(5200); await allStopped();
  await page.locator('#cal-link').click();
  mark('replay starts at zero; navigating away cancels queue');

  // Browser autoplay rejection and async promise races, scoped to the test page.
  await page.evaluate(()=>{
    window.qaPlay=HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play=function(){return Promise.reject(new DOMException('test','NotAllowedError'));};
  });
  await choose('en_eng','ab'); await idle();
  assert.match(await page.locator('#cal-status').innerText(),/浏览器未允许播放/); await allStopped();
  await page.evaluate(()=>{HTMLMediaElement.prototype.play=qaPlay;});
  await choose('en_eng','a'); await moving(); await idle();
  mark('autoplay rejection feedback and manual retry');

  await page.evaluate(()=>{
    const v=getCalVideo('an_ang','a');
    v.play=()=>new Promise((_,reject)=>{window.qaReject=reject;});
  });
  await choose('an_ang','ab');
  await choose('en_eng','b'); await moving();
  await page.evaluate(()=>{qaReject(new DOMException('test','AbortError'));delete getCalVideo('an_ang','a').play;});
  assert.equal(await page.locator('.cal-card.playing video').getAttribute('data-final'),'eng');
  await idle();mark('late play rejection cannot stop a newer selection');

  await page.evaluate(()=>{const v=getCalVideo('in_ing','a');v.src='/assets/calibration/missing-test.mp4';v.load();});
  await choose('in_ing','ab');await idle();
  assert.match(await page.locator('#cal-status').innerText(),/失败/);await allStopped();
  await page.evaluate(()=>{const v=getCalVideo('in_ing','a');v.src=calVideoUrl('in');v.load();});
  await choose('in_ing','a');await moving();await idle();
  mark('missing media reports failure, no next clip, retry succeeds');

  await choose('an_ang','ab');await moving();
  await page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pagehide')));await allStopped();
  await choose('en_eng','ab');await moving();
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));delete document.hidden;});await allStopped();
  mark('pagehide and hidden-page handlers stop playback (simulated browser events)');
  assert.deepEqual(await page.evaluate(()=>qaOverlaps),[]);
  mark('no overlapping videos during all flows');

  await page.locator('[data-cal-speed="normal"]').focus(); await page.keyboard.press('Enter');
  await page.locator('[data-cal-group="an_ang"]').click();
  await button('an_ang','a').focus(); await page.keyboard.press('Space');await moving();
  await page.locator('#cal-stop').focus();await page.keyboard.press('Enter');await allStopped();
  mark('keyboard Enter and Space activate speed, playback and stop');

  for(const width of [360,390,430,600,1024]){
    await page.setViewportSize({width,height:900});
    await page.evaluate(()=>window.scrollTo(0,0));await page.waitForTimeout(300);
    const layout=await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
      videos:[...document.querySelectorAll('#cal-groups video')].filter(v=>v.getBoundingClientRect().width).map(v=>{const r=v.getBoundingClientRect();return {w:r.width,h:r.height,fit:getComputedStyle(v).objectFit,sourceWidth:v.videoWidth,sourceHeight:v.videoHeight};}),
      buttons:[...document.querySelectorAll('#view-calibration button')].filter(b=>b.getBoundingClientRect().width).map(b=>({text:b.textContent.trim(),w:b.getBoundingClientRect().width,h:b.getBoundingClientRect().height}))}));
    assert(layout.scrollWidth<=width);
    assert(layout.buttons.every(b=>b.h>=44 && b.w>=44));
    assert(layout.videos.every(v=>Math.abs(v.w/v.h-16/9)<.02 && v.fit==='contain' && v.sourceWidth===1920));
    report.layouts.push(layout);
    await page.screenshot({path:path.join(out,'screenshots',`page-${width}.png`),fullPage:true});
  }
  await page.setViewportSize({width:390,height:844});
  for(const [i,group] of ['an_ang','en_eng','in_ing'].entries()){
    await page.locator(`[data-cal-group="${group}"]`).click();
    const section=page.locator('.cal-group').nth(i);
    await section.screenshot({path:path.join(out,'screenshots',`${group}-normal.png`)});
  }
  await page.locator('[data-cal-speed="slow"]').click();
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,'screenshots','half-speed-390.png'),fullPage:true});
  mark('360/390/430/600/1024 layout, full 16:9 frame, 44px controls, local-only resources');
  assert.deepEqual(report.errors,[]);
  report.status='passed';
})().catch(e=>{report.status='failed';report.failure=e.stack;console.error(e);process.exitCode=1;}).finally(async()=>{
  fs.writeFileSync(path.join(out,'browser-report.json'),JSON.stringify(report,null,2));
  if(browser)await browser.close();
});
