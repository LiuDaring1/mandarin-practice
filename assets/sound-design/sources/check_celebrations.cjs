/* v2-only acceptance. Original runtime and v1 behavior checks are preserved in versions/v1. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve(__dirname,'../qa/celebration-v2'),url='http://127.0.0.1:8772';
const report={checks:[],errors:[],layouts:[]};const mark=(name,detail=true)=>{report.checks.push({name,detail});console.log('PASS',name);};let browser;
(async()=>{
 const info=await(await fetch(url+'/__qa/info')).json();assert(info.read_only&&info.kind==='sound-lab');
 browser=await chromium.launch({channel:'chrome',headless:true});const context=await browser.newContext({viewport:{width:1024,height:900}});const page=await context.newPage();
 page.on('pageerror',e=>report.errors.push(e.message));page.on('request',r=>{assert.equal(r.method(),'GET');assert(r.url().startsWith(url));});
 await page.goto(url+'/index.html?round=2#celebrations');await page.waitForFunction(()=>window.soundLab);
 assert.equal(await page.evaluate(()=>soundLab.getState().celebration),'lift');assert.equal(await page.locator('#celebration-grid button').count(),8);assert.equal(await page.locator('#sound-grid .sound-card').count(),7);mark('A 已确认；四项原版/新版对比与七种日常音分别呈现');
 await page.locator('[data-celebration="reward.arrive"][data-version="lift"]').click();await page.waitForFunction(()=>soundLab.getState().loaded===27&&soundLab.getState().active>0);mark('真实点击解锁并解码 27 个运行时样本');
 await page.waitForTimeout(1000);
 const ids=['reward.arrive','day.complete','artwork.complete','series.complete'];
 for(const id of ids)for(const version of ['original','lift']){
  await page.evaluate(()=>{soundLab.sound.history=[];soundLab.sound.last.clear();});await page.locator(`[data-celebration="${id}"][data-version="${version}"]`).click();
  await page.waitForFunction(([id,style])=>soundLab.getState().history.some(e=>e.action==='played'&&e.id===id&&e.style===style),[id,version==='lift'?'a-lift':'a']);
  await page.waitForFunction(()=>soundLab.getState().active===0);
 }
 mark('八个原版/新版按钮实际播放到 ended，没有覆盖原版');
 await page.evaluate(()=>{soundLab.sound.history=[];soundLab.sound.last.clear();});await page.locator('#celebration-reel').click();
 await page.waitForFunction(()=>document.querySelector('#celebration-feedback').textContent.startsWith('新版四段播放完毕'),{},{timeout:14000});
 const reel=await page.evaluate(()=>soundLab.getState().history.filter(e=>e.action==='played').map(e=>[e.id,e.style]));assert.deepEqual(reel,ids.map(id=>[id,'a-lift']));mark('四段连续试听按顺序完整播放',reel);
 for(const v of ['original','lift']){
  await page.locator(`input[name="celebration"][value="${v}"]`).check();
  for(const series of [false,true]){
   await page.locator('#series').setChecked(series);await page.evaluate(()=>{soundLab.sound.history=[];soundLab.sound.last.clear();});await page.locator('#ceremony').click();
   const id=series?'series.complete':'artwork.complete';const expected=v==='lift'?'a-lift':'a';
   await page.waitForFunction(([id,style])=>soundLab.getState().history.some(e=>e.action==='played'&&e.id===id&&e.style===style),[id,expected]);
   const h=await page.evaluate(()=>soundLab.getState().history.filter(e=>e.action==='played'));
   assert(h.some(e=>e.id==='artwork.fuse'&&e.style==='a'));assert(!h.some(e=>e.id===(series?'artwork.complete':'series.complete')));
   await page.locator('#stop').click();await page.waitForTimeout(40);
  }
 }
 mark('完成仪式遵循新版/原版切换；融合仍用 A，系列与单件互斥');
 await page.evaluate(()=>{soundLab.sound.history=[];});await page.locator('#quiz').click();
 await page.waitForFunction(()=>soundLab.getState().history.some(e=>e.action==='played'&&e.id==='reward.arrive'),{},{timeout:14000});
 const quiz=await page.evaluate(()=>soundLab.getState().history.filter(e=>e.action==='played'));
 assert.equal(quiz.filter(e=>e.id==='answer.correct'&&e.style==='a').length,7);assert.equal(quiz.filter(e=>e.id==='answer.retry'&&e.style==='a').length,3);assert(quiz.some(e=>e.id==='reward.arrive'&&e.style==='a-lift'));
 mark('答题反馈仍是已认可 A，结算自动采用新版欢庆');
 await page.locator('#stop').click();await page.waitForTimeout(40);
 await page.locator('#teaching').click();await page.waitForFunction(()=>soundLab.getState().teaching>0);
 await page.locator('#intrude').click();assert((await page.locator('#teaching-state').innerText()).includes('已丢弃'));await page.locator('#stop').click();mark('更长的庆祝音仍服从教学优先');
 await page.waitForTimeout(150);await page.evaluate(()=>{soundLab.sound.last.clear();});await page.locator('[data-celebration="series.complete"][data-version="lift"]').click();await page.waitForFunction(()=>soundLab.getState().active>0);await page.locator('#mute').click();await page.waitForTimeout(40);
 assert.equal(await page.evaluate(()=>soundLab.getState().active),0);await page.locator('#mute').click();await page.waitForTimeout(120);assert.equal(await page.evaluate(()=>soundLab.getState().active),0);mark('新增长尾庆祝可立即静音，重新开启不补播');
 for(const width of [360,390,430,768,1024]){
  await page.setViewportSize({width,height:900});await page.evaluate(()=>document.querySelector('#celebrations').scrollIntoView());
  const data=await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth}));assert(data.scrollWidth<=width);report.layouts.push(data);
  await page.screenshot({path:path.join(out,`celebrations-${width}.png`)});
 }
 mark('庆祝对比区五档宽度无横向溢出');
 assert.deepEqual(report.errors,[]);report.status='passed';
})().catch(e=>{report.status='failed';report.failure=e.stack;console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();fs.writeFileSync(path.join(out,'browser-report.json'),JSON.stringify(report,null,2)+'\n');});
