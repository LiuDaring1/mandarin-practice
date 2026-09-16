const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const innerHeightValue=()=>844;
const out=path.resolve(__dirname,'../handoff/calibration-mobile-2026-09-12');
(async()=>{
  const url='http://127.0.0.1:8771';assert((await(await fetch(url+'/__qa/info')).json()).isolated);
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage();await page.goto(url+'/?view=calibration');await page.waitForSelector('.cal-group');
    const layouts=[];
    for(const width of [360,390,430,600,1024]){
      await page.setViewportSize({width,height:844});await page.waitForTimeout(200);
      const result=await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,pageHeight:document.documentElement.scrollHeight,viewportHeight:innerHeight,visibleGroups:document.querySelectorAll('.cal-group:not([hidden])').length,controlBottom:document.querySelector('#cal-stop').getBoundingClientRect().bottom,
        buttons:[...document.querySelectorAll('#view-calibration button')].filter(b=>b.getBoundingClientRect().width).map(b=>{const r=b.getBoundingClientRect();return {text:b.textContent,w:r.width,h:r.height};}),
        videos:[...document.querySelectorAll('#cal-groups video')].filter(v=>v.getBoundingClientRect().width).map(v=>{const r=v.getBoundingClientRect();return {w:r.width,h:r.height,fit:getComputedStyle(v).objectFit};}),
        toolbarHeight:document.querySelector('.cal-toolbar').getBoundingClientRect().height}));
      assert(result.scrollWidth<=width);assert(result.buttons.every(b=>b.w>=44&&b.h>=44));
      assert(result.videos.every(v=>v.fit==='contain'&&Math.abs(v.w/v.h-16/9)<.02));assert(result.toolbarHeight<=54);assert.equal(result.visibleGroups,1);assert.equal(result.videos.length,1);assert(result.controlBottom<innerHeightValue(width));
      layouts.push(result);await page.screenshot({path:path.join(out,'screenshots',`page-${width}.png`),fullPage:true});
    }
    await page.setViewportSize({width:390,height:844});
    for(const [i,group] of ['an_ang','en_eng','in_ing'].entries()){await page.locator(`[data-cal-group="${group}"]`).click();await page.screenshot({path:path.join(out,'screenshots',`${group}-normal.png`),fullPage:true});}
    await page.locator('[data-cal-speed="slow"]').click();await page.evaluate(()=>scrollTo(0,0));
    await page.screenshot({path:path.join(out,'screenshots','half-speed-390.png'),fullPage:true});
    // Freeze genuinely played slow animation during nasal closure for frame review.
    for(const group of ['an_ang','en_eng','in_ing']){
      await page.locator(`[data-cal-group="${group}"]`).click();
      await page.locator(`button[data-group="${group}"][data-seq="b"]`).click();
      await page.waitForFunction(g=>getCalVideo(g,'b').currentTime>1.2,group);
      await page.evaluate(g=>getCalVideo(g,'b').pause(),group);
      await page.locator(`.cal-card[data-group="${group}"][data-side="b"]`).screenshot({path:path.join(out,'screenshots',`${group}-slow-closure.png`)});
    }
    fs.writeFileSync(path.join(out,'final-layout-report.json'),JSON.stringify({status:'passed',layouts},null,2));console.log('PASS final layout and active closure screenshots');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
