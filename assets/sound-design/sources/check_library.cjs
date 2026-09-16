const {chromium}=require('playwright'), assert=require('node:assert/strict'), fs=require('node:fs'), path=require('node:path');
const base='http://127.0.0.1:8772',out=path.resolve(__dirname,'../qa/library-v3');
const report={checks:[],layouts:[],errors:[],localRequests:[],externalPlayers:[]};
const mark=(name,detail=true)=>{report.checks.push({name,detail});console.log('PASS',name);};
let browser;
(async()=>{
 const info=await(await fetch(base+'/__qa/info')).json();assert(info.read_only&&info.isolated&&info.progress_dir===null);mark('独立只读服务');
 for(const route of ['/external/dustyroom/DM-CGS.zip','/external/dustyroom/DM-CGS-00.wav','/external/dustyroom/DM-CGS-51.wav','/external/dustyroom/../../manifest.json','/data/derived/prototype/discrim_progress.json']) {
  // Encoded traversal must be rejected before path normalization.
  if(route.includes('../'))continue;
  assert.equal((await fetch(base+route)).status,404);
 }
 assert.equal((await fetch(base+'/external/dustyroom/%2e%2e%2f%2e%2e%2fmanifest.json')).status,404);
 assert.equal((await fetch(base+'/external/dustyroom/LICENSE.txt')).status,200);mark('白名单拒绝原 ZIP、越界编号、路径穿越与真实数据');
 browser=await chromium.launch({channel:'chrome',headless:true});
 const context=await browser.newContext({viewport:{width:1024,height:900}}),page=await context.newPage();
 page.on('pageerror',e=>report.errors.push(e.message));page.on('request',r=>{assert(r.url().startsWith(base)||r.url().startsWith('data:'));if(r.url().startsWith(base))report.localRequests.push({url:r.url(),method:r.method()});});
 await page.goto(base+'/library.html?round=3');await page.waitForFunction(()=>window.libraryLab?.getState().ready===90);
 assert.equal(await page.locator('#quick-samples button').count(),6);assert.equal(await page.locator('#all-samples button').count(),50);
 assert.equal(await page.locator('iframe').count(),0);assert.equal(await page.locator('[data-demo]').count(),0);assert.equal(await page.evaluate(()=>libraryLab.getState().playing),false);mark('90 个免费原音就绪，页面无付费项或第三方播放器、不自动播放');
 const decoded=await page.evaluate(async()=>{const data=await(await fetch('/library-manifest.json')).json(),ac=new AudioContext();const records=await Promise.all([...data.samples,...data.extra_samples].map(async s=>{const r=await fetch(s.url);if(!r.ok)throw Error(s.url);const b=await ac.decodeAudioData(await r.arrayBuffer());return {number:s.number,channels:b.numberOfChannels,duration:b.duration};}));await ac.close();return records;});
 assert.equal(decoded.length,90);assert(decoded.slice(0,50).every(s=>s.channels===2&&s.duration>0));assert(decoded.slice(50).every(s=>s.channels===1&&s.duration>0));mark('90 个原始 PCM24 WAV 在浏览器成功解码，声道保留',decoded.length);
 await page.locator('#quick-samples [data-sample="5"]').click();await page.waitForFunction(()=>libraryLab.getState().playing);
 await page.waitForFunction(()=>libraryLab.getState().history.some(e=>e.type==='ended'&&e.id===5));mark('真实点击单音播放并自然结束');
 await page.locator('#reel').click();await page.waitForFunction(()=>document.querySelector('#status').textContent.startsWith('6 个原音播放完毕'),null,{timeout:20000});
 const ended=await page.evaluate(()=>libraryLab.getState().history.filter(e=>e.type==='ended').slice(-6).map(e=>e.id));assert.deepEqual(ended,[2,7,5,23,11,49]);mark('六段顺序试听完成',ended);
 await page.locator('#reel').click();await page.waitForFunction(()=>libraryLab.getState().playing);await page.locator('#stop').click();
 const count=await page.evaluate(()=>libraryLab.getState().history.length);await page.waitForTimeout(1100);
 assert.equal(await page.evaluate(()=>libraryLab.getState().history.length),count);assert.equal(await page.evaluate(()=>libraryLab.getState().playing),false);mark('停止取消正在播放的声音与后续队列');
 await page.locator('#quick-samples [data-sample="11"]').click();await page.locator('#quick-samples [data-sample="49"]').click();await page.waitForFunction(()=>libraryLab.getState().current===49);
 await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>libraryLab.getState().playing),false);mark('切换单音互斥，Escape 停止');
 await page.locator('#volume').fill('23');assert.equal(await page.evaluate(()=>libraryLab.audio.volume),0.23);mark('本地音量实时生效');
 assert.equal(await page.locator('#cute-samples button').count(),8);assert.equal(await page.locator('#cute-all button').count(),40);
 await page.locator('#cute-reel').click();await page.waitForFunction(()=>document.querySelector('#status').textContent.startsWith('6 个原音播放完毕'),null,{timeout:15000});
 assert.deepEqual(await page.evaluate(()=>libraryLab.getState().history.filter(e=>e.type==='ended').slice(-6).map(e=>e.id)),[103,106,105,121,125,130]);mark('第二套免费 Cute UI 六段连听完成');
 await page.locator('#cute-samples [data-sample="121"]').click();await page.locator('#quick-samples [data-sample="11"]').click();await page.waitForFunction(()=>libraryLab.getState().current===11);await page.locator('#stop').click();mark('两套本地素材切换互斥并可停止');
 assert(!await page.locator('body').innerText().then(t=>/US\$|SwishSwoosh|BOOM Library|官方演示/.test(t)));mark('当前页面不展示付费音库');
 assert.equal(await page.evaluate(()=>localStorage.length),0);mark('不写浏览器存储');
 for(const width of [360,390,768,1024]) {
  await page.setViewportSize({width,height:900});await page.screenshot({path:path.join(out,'library-'+width+'.png'),fullPage:true});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);assert(!overflow);report.layouts.push({width,overflow});
 }mark('四档布局无横向溢出');
 await page.goto(base+'/index.html');await page.waitForFunction(()=>window.soundLab);
 assert.match(await page.locator('body').innerText(),/已根据反馈否决/);await page.locator('[data-celebration="reward.arrive"][data-version="original"]').click();
 await page.waitForFunction(()=>soundLab.getState().history.some(e=>e.action==='played'&&e.id==='reward.arrive'&&e.style==='a'));await page.locator('#stop').click();mark('历史页明确标记否决，原 A 样音仍可播放');
 assert(report.localRequests.every(r=>r.method==='GET'));assert.equal(report.errors.length,0);mark('本地只读请求，无页面脚本错误');
 await context.close();await browser.close();browser=null;
 fs.writeFileSync(path.join(out,'browser-report.json'),JSON.stringify(report,null,2));console.log('COMPLETE',report.checks.length);
})().catch(async e=>{report.failure=e.stack;fs.writeFileSync(path.join(out,'browser-report.json'),JSON.stringify(report,null,2));console.error(e);await browser?.close();process.exitCode=1;});
