// Run after the other two browser scripts; use a fresh isolated server to avoid intentionally delayed backlog.
const spaceId=Number(process.env.PTH_QA_SPACE);if(!spaceId)throw new Error('Set PTH_QA_SPACE to the existing browser TaskSpace id');
const task=await taskSpace(spaceId),page=task.page('p1');
await page.reload();await page.waitForFunction(()=>!!state.home);
await page.cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
await page.evaluate(()=>{
 const Original=AudioContext;window.AudioContext=new Proxy(Original,{construct(T,args){const c=Reflect.construct(T,args);window.qaContext=c;return c;}});
 navigator.mediaDevices.getUserMedia=async()=>{const c=qaContext,o=c.createOscillator(),g=c.createGain(),d=c.createMediaStreamDestination();g.gain.value=.15;o.connect(g);g.connect(d);o.start();return d.stream;};
});
await page.evaluate(async()=>await fetch('/__qa/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({delay:8,status:'ok'})}));
await page.click('loc=role:button[name="字词"]');await page.mouse.wheel(0,320,{label:'查看开始练习按钮'});await page.click('#start-btn');
await page.waitForFunction(()=>state.mode==='waiting_follow',undefined,{timeout:25000});
await page.evaluate(()=>{window.qaBegin=qaContext.currentTime;state.session.items=state.session.items.slice(0,2);});
await page.waitForFunction(()=>qaContext.currentTime-qaBegin>.4);
await page.click('#reading-done-word');await page.waitForFunction(()=>state.index===1);
if(await page.evaluate(()=>document.getElementById('assessment-word').textContent.includes('分')))throw new Error('word score interrupt');
console.log('PASS word advance does not wait for assessment');
const oldId=await page.evaluate(async()=>{
 for(let i=0;i<50;i++){
  const r=await(await fetch('/api/reading/review')).json();if(r.sessions[0]?.pending)return r.sessions[0].session_id;
  await new Promise(r=>setTimeout(r,20));
 }throw new Error('no accepted background job');
});
await page.evaluate(()=>resetToHome());await page.mouse.wheel(0,320,{label:'查看开始练习按钮'});await page.click('#start-btn');await page.waitForFunction(()=>state.mode==='playing_reference');await page.click('#pause-btn');
await page.waitForFunction(async(id)=>!(await(await fetch('/api/reading/session/'+id)).json()).pending,oldId,{timeout:25000});
if(!await page.evaluate(()=>state.index===0&&state.mode==='paused'&&!document.querySelector('#view-training .reading-summary')) )throw new Error('stale result changed new run');
console.log('PASS late result leaves newer run untouched');
await page.evaluate(()=>resetToHome());
const p2=await task.newPage();await p2.goto('http://127.0.0.1:8777/');await p2.waitForFunction(()=>!!state.home);
await p2.click('loc=role:button[name="句子"]');await p2.mouse.wheel(0,350,{label:'查看朗读回顾'});await p2.click('#reading-review-btn');
await p2.waitForFunction(()=>document.getElementById('complete-body').textContent.includes('鼻音诊断仍在验证'));
if(await p2.evaluate(()=>document.getElementById('complete-body').textContent.includes('开始专项复练')))throw new Error('unvalidated automatic practice exposed');
console.log('PASS production gate hides unvalidated weak-item actions');
console.log(await p2.snapshot());
const fs=await import('node:fs/promises');const file=process.cwd()+'/handoff/continuous-reading-2026-10-23/ui-report.json';
const report=JSON.parse(await fs.readFile(file,'utf8'));report.checks.push('word advance does not wait for assessment','late result leaves newer run untouched','production gate hides unvalidated weak-item actions','synthetic original-sentence and same-final review pipeline');await fs.writeFile(file,JSON.stringify(report,null,2));
