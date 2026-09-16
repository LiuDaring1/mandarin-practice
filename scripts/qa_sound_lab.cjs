/* Sound lab only. New browser context; refuses training server; no autoplay bypass. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const root=path.resolve(__dirname,'..'),out=path.join(root,'assets/sound-design/qa');
const url='http://127.0.0.1:8772';const report={checks:[],layouts:[],errors:[],requests:[]};
const mark=(name,detail=true)=>{report.checks.push({name,detail});console.log('PASS',name);};
let browser,page;
(async()=>{
 const isolation=await(await fetch(url+'/__qa/info')).json();assert(isolation.isolated&&isolation.read_only&&isolation.kind==='sound-lab'&&isolation.progress_dir===null);
 mark('独立只读服务，不加载训练或进度 API',isolation);
 browser=await chromium.launch({channel:'chrome',headless:true});
 const context=await browser.newContext({viewport:{width:1024,height:900}});
 page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));
 page.on('request',r=>{report.requests.push({method:r.method(),url:r.url()});assert.equal(r.method(),'GET');assert(r.url().startsWith(url));});
 await page.goto(url+'/index.html');await page.waitForFunction(()=>window.soundLab);
 const runtimeSampleCount=await page.evaluate(()=>soundLab.sound.manifest.sounds.reduce((n,s)=>n+s.variants.length,0));
 assert.equal(await page.evaluate(()=>soundLab.getState().state),'locked');mark('首次加载不自动播放，不创建运行中的 AudioContext');
 await page.locator('.archive-comparison').evaluate(e=>{e.open=true;});await page.getByRole('button',{name:'A 组 轻点',exact:true}).click();
 await page.waitForFunction(n=>soundLab.getState().state==='running'&&soundLab.getState().loaded===n,runtimeSampleCount);
 mark('真实用户点击解锁，全部运行时样本成功解码');
 await page.waitForTimeout(120);
 const energy=await page.evaluate(async()=>{
   const s=soundLab.sound,a=s.ctx.createAnalyser();a.fftSize=1024;s.master.connect(a);
   s.play('answer.correct');let peak=0;const samples=new Float32Array(1024);
   for(let i=0;i<16;i++){await new Promise(r=>setTimeout(r,12));a.getFloatTimeDomainData(samples);peak=Math.max(peak,...samples.map(Math.abs));}
   s.master.disconnect(a);return peak;
 });assert(energy>.005&&energy<.25);mark('Web Audio 输出链有非零音频能量（不等于人耳验收）',{peak:energy});
 // Decode and play every declared sample to its actual ended callback.
 const played=await page.evaluate(async()=>{
   const s=soundLab.sound;let count=0;s.stopAll(true);s.last.clear();
   for(const def of s.manifest.sounds){
     for(let i=0;i<def.variants.length;i++){
       const h=s.play(def.id,{style:def.style,variant:i,optional:true});if(!h.started)throw Error(def.id+':'+h.reason);
       await h.done;count++;
       if(def.variants.length>1)await new Promise(r=>setTimeout(r,110));
     }
   }return count;
 });assert.equal(played,runtimeSampleCount);mark('每个样本实际 start → ended，释放音源节点',played);
 // New transient IDs; exact deduplication and optional cue rule.
 const dedup=await page.evaluate(async()=>{
   const s=soundLab.sound;s.last.clear();s.play('ui.confirm',{eventKey:'qa-only-once'});await new Promise(r=>setTimeout(r,120));
   return {duplicate:s.play('ui.confirm',{eventKey:'qa-only-once'}).reason,optional:s.play('follow.ready').reason};
 });assert.deepEqual(dedup,{duplicate:'duplicate',optional:'optional-off'});mark('事件去重与默认关闭的跟读提示',dedup);
 await page.locator('#quiz').click();await page.waitForFunction(()=>document.querySelector('#stage-tag').textContent==='答题模拟完成');
 const quiz=await page.evaluate(()=>soundLab.getState().history.filter(e=>e.action==='played'&&['answer.correct','answer.retry'].includes(e.id)).slice(-10).map(e=>e.id));
 assert.equal(quiz.filter(x=>x==='answer.retry').length,3);assert.equal(quiz.filter(x=>x==='answer.correct').length,7);mark('密集 10 题预设正误，连错没有警报升级',quiz);
 await page.waitForTimeout(700);
 await page.evaluate(()=>{soundLab.sound.history=[];});await page.locator('#beads10').click();
 await page.waitForFunction(()=>document.querySelector('#stage-tag').textContent==='连续拼入完成',{},{timeout:14000});
 const bead=await page.evaluate(()=>{const s=soundLab.getState();const ticks=s.history.filter(x=>x.action==='played'&&x.id==='bead.place');return {ticks:ticks.length,placed:s.beadCount,minInterval:Math.min(...ticks.slice(1).map((x,i)=>x.time-ticks[i].time)),variants:[...new Set(ticks.map(x=>x.variant))],maxObserved:s.maxObserved,active:s.active};});
 assert(bead.ticks>=70&&bead.ticks<=101);assert(bead.placed>bead.ticks);assert(bead.minInterval>=99);assert.equal(bead.variants.length,6);assert(bead.maxObserved<=4);
 await page.waitForTimeout(150);assert.equal(await page.evaluate(()=>soundLab.getState().active),0);mark('10 秒加速拼豆，音符限流、六变体、无积压',bead);
 // Real pointer capture / release, then keyboard hold.
 const hold=page.locator('#hold');await hold.scrollIntoViewIfNeeded();let box=await hold.boundingBox();
 await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();await page.waitForTimeout(800);
 assert(await page.evaluate(()=>soundLab.getState().holding));await page.mouse.up();
 const count=await page.evaluate(()=>soundLab.getState().beadCount);await page.waitForTimeout(200);
 assert.deepEqual(await page.evaluate(()=>[soundLab.getState().holding,soundLab.getState().beadCount,soundLab.getState().active]),[false,count,0]);mark('真实长按松手立即停，计数与音源不继续');
 await hold.focus();await page.keyboard.down('Space');await page.waitForTimeout(550);assert(await page.evaluate(()=>soundLab.getState().holding));await page.keyboard.up('Space');await page.waitForTimeout(80);assert.equal(await page.evaluate(()=>soundLab.getState().holding),false);
 await page.keyboard.down('Enter');await page.waitForTimeout(380);await page.keyboard.up('Enter');await page.waitForTimeout(80);assert.equal(await page.evaluate(()=>soundLab.getState().active),0);mark('Space / Enter 按下和释放，不产生键盘重复队列');
 // Ceremony and replacement for the final series.
 await page.locator('#ceremony').click();await page.waitForFunction(()=>document.querySelector('#stage-title').textContent==='一件小作品，完成了。');await page.waitForTimeout(1250);
 await page.locator('#series').check();await page.evaluate(()=>{soundLab.sound.history=[];});await page.locator('#ceremony').click();
 await page.waitForFunction(()=>document.querySelector('#stage-title').textContent==='猫猫系列，集齐啦。');
 const ceremony=await page.evaluate(()=>soundLab.getState().history.filter(e=>e.action==='played').map(e=>e.id));
 assert(ceremony.includes('artwork.fuse')&&ceremony.includes('series.complete')&&!ceremony.includes('artwork.complete'));mark('1.8 秒融合及系列音替代单件庆祝',ceremony);
 await page.locator('#stop').click();await page.waitForTimeout(40);
 await page.evaluate(()=>{soundLab.sound.history=[];});await page.locator('#teaching').click();
 await page.waitForFunction(()=>document.querySelector('#voice').currentTime>.05&&!document.querySelector('#voice').paused);
 await page.locator('#intrude').click();
 assert((await page.locator('#teaching-state').innerText()).includes('已丢弃'));
 await page.waitForFunction(()=>document.querySelector('#stage-tag').textContent==='教学衔接完成');
 const teaching=await page.evaluate(()=>soundLab.getState().history);assert(!teaching.some(x=>x.action==='played'&&['reward.arrive','answer.correct','follow.ready'].includes(x.id)));
 mark('实际示范播放优先，奖励丢弃不补播；跟读结束安静',teaching);
 // Optional cue enabled, only after ended + margin.
 await page.locator('#follow-cue').check();await page.evaluate(()=>{soundLab.sound.history=[];});await page.locator('#teaching').click();
 await page.waitForFunction(()=>document.querySelector('#stage-tag').textContent==='教学衔接完成');
 assert.equal(await page.evaluate(()=>soundLab.getState().history.filter(x=>x.action==='played'&&x.id==='follow.ready').length),1);mark('可选跟读提示开启后仅一次，计时结束不响');
 // Mute keeps teaching audio and visible simulations working.
 await page.locator('#mute').click();await page.evaluate(()=>{soundLab.sound.history=[];});await page.locator('#teaching').click();
 await page.waitForFunction(()=>document.querySelector('#voice').currentTime>.05&&!document.querySelector('#voice').paused);
 assert.equal(await page.evaluate(()=>document.querySelector('#voice').volume),1);
 assert.equal(await page.evaluate(()=>soundLab.getState().history.filter(x=>x.action==='played').length),0);
 await page.locator('#stop').click();mark('关闭音效不关闭或压低教学音频，全部停止可停示范');
 await page.locator('#mute').click();await page.locator('#volume').focus();await page.keyboard.press('Home');
 assert.equal(await page.evaluate(()=>soundLab.getState().preferences.volume),0);
 await page.keyboard.press('ArrowRight');assert.equal(await page.evaluate(()=>soundLab.getState().preferences.volume),.01);
 await page.keyboard.press('End');for(let i=0;i<30;i++)await page.keyboard.press('ArrowLeft');mark('音量 0 静音，滑杆键盘可调整');
 // Suspension and hidden lifecycle simulated deliberately, recorded as such.
 await page.locator('#beads10').click();await page.waitForTimeout(350);
 await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'));});
 await page.waitForTimeout(60);assert.equal(await page.evaluate(()=>soundLab.getState().holding),false);assert.equal(await page.evaluate(()=>soundLab.getState().state),'suspended');assert.equal(await page.evaluate(()=>soundLab.getState().active),0);
 const before=await page.evaluate(()=>soundLab.getState().history.filter(e=>e.action==='played').length);
 await page.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));});await page.waitForTimeout(300);
 assert.equal(await page.evaluate(()=>soundLab.getState().history.filter(e=>e.action==='played').length),before);
 await page.locator('.archive-comparison').evaluate(e=>{e.open=true;});await page.getByRole('button',{name:'A 组 轻点',exact:true}).click();await page.waitForFunction(()=>soundLab.getState().state==='running');
 mark('模拟 visibilitychange：挂起、取消流程、回来不补播，点击恢复');
 // Real AudioContext suspend/resume without lifecycle spoof.
 await page.evaluate(()=>soundLab.sound.ctx.suspend());assert.equal(await page.evaluate(()=>soundLab.sound.play('ui.confirm').reason),'inactive');
 await page.locator('.archive-comparison').evaluate(e=>{e.open=true;});await page.getByRole('button',{name:'A 组 答对',exact:true}).click();await page.waitForFunction(()=>soundLab.getState().state==='running');mark('真实 AudioContext suspend / 手势 resume');
 await page.locator('#stop').click();
 // Preferences survive reload; unrelated localStorage sentinel untouched.
 await page.evaluate(()=>localStorage.setItem('qa-unrelated-sentinel','unchanged'));await page.reload();await page.waitForFunction(()=>window.soundLab);
 assert.equal(await page.evaluate(()=>soundLab.getState().preferences.volume),.7);assert.equal(await page.evaluate(()=>localStorage.getItem('qa-unrelated-sentinel')),'unchanged');
 const keys=await page.evaluate(()=>Object.keys(localStorage));assert.deepEqual(keys.sort(),['pth-sound-lab-preferences-v1','qa-unrelated-sentinel'].sort());mark('只写独立音效偏好键，不写训练存储键',keys);
 for(const width of [360,390,430,768,1024]){
  await page.setViewportSize({width,height:900});await page.evaluate(()=>scrollTo(0,0));await page.waitForTimeout(120);
  const geometry=await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth}));assert(geometry.scrollWidth<=width);
  report.layouts.push(geometry);await page.screenshot({path:path.join(out,`page-${width}.png`),fullPage:true});
 }
 mark('360 / 390 / 430 / 768 / 1024 无横向溢出');
 await page.emulateMedia({reducedMotion:'reduce'});assert.equal(await page.locator('.bead-board').evaluate(e=>getComputedStyle(e).animationName),'none');mark('减少动态效果模式');
 await page.locator('.archive-comparison').evaluate(e=>{e.open=true;});await page.getByRole('button',{name:'A 组 轻点',exact:true}).click();await page.waitForFunction(()=>soundLab.getState().state==='running');
 await page.evaluate(()=>soundLab.dispose());assert.equal(await page.evaluate(()=>soundLab.getState().state),'closed');mark('销毁关闭 AudioContext 与缓存');
 assert.deepEqual(report.errors,[]);report.status='passed';await browser.close();
})().catch(async e=>{report.status='failed';report.failure=e.stack;console.error(e);await browser?.close();process.exitCode=1;}).finally(()=>{fs.writeFileSync(path.join(out,'browser-report.json'),JSON.stringify(report,null,2)+'\n');});
