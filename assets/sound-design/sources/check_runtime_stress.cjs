/* Optional supplemental QA: run with bundled Node and NODE_PATH, server on 8772. */
const {chromium}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const url='http://127.0.0.1:8772';const info=await(await fetch(url+'/__qa/info')).json();assert(info.read_only&&info.kind==='sound-lab');
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:900,height:900}}),page=await context.newPage();
  await page.goto(url+'/index.html');await page.waitForFunction(()=>window.soundLab);
  await page.locator('.archive-comparison').evaluate(e=>{e.open=true;});
  const target=page.getByRole('button',{name:'A 组 轻点',exact:true});await target.click();await page.waitForFunction(()=>soundLab.getState().loaded===soundLab.sound.manifest.sounds.reduce((n,s)=>n+s.variants.length,0));
  await page.waitForTimeout(120);await page.evaluate(()=>{soundLab.sound.history=[];soundLab.sound.last.clear();});
  const box=await target.boundingBox();for(let i=0;i<16;i++)await page.mouse.click(box.x+box.width/2,box.y+box.height/2);
  await page.waitForTimeout(180);const rapid=await page.evaluate(()=>{const s=soundLab.getState();return {played:s.history.filter(e=>e.action==='played').length,dropped:s.history.filter(e=>e.action==='dropped'&&e.reason==='rate-limit').length,active:s.active,maxObserved:s.maxObserved};});
  assert(rapid.played>=1&&rapid.dropped>=1&&rapid.active===0&&rapid.maxObserved<=4);
  const priority=await page.evaluate(async()=>{const s=soundLab.sound;s.stopAll(true);s.last.clear();s.play('reward.arrive');const a=s.play('answer.retry');const b=s.play('ui.confirm');await new Promise(r=>setTimeout(r,30));return {feedbackStarted:a.started,clickDropped:b.reason,active:s.active.size};});
  assert(priority.feedbackStarted&&priority.clickDropped==='priority');await page.evaluate(()=>soundLab.dispose());
  const report={status:'passed',rapid,priority};fs.writeFileSync(path.resolve(__dirname,'../qa/stress-report.json'),JSON.stringify(report,null,2)+'\n');console.log(report);
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
