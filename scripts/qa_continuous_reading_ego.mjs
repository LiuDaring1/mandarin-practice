// Run with ego-browser nodejs; only the disposable server and generated tone input.
const spaceId=Number(process.env.PTH_QA_SPACE);if(!spaceId)throw new Error('Set PTH_QA_SPACE to the existing browser TaskSpace id');
const task=await taskSpace(spaceId),page=task.page('p1');
const fs=await import('node:fs/promises');
const out=process.cwd()+'/handoff/continuous-reading-2026-10-23';
await fs.mkdir(out,{recursive:true});
const checks=[];
function check(ok,name){if(!ok)throw new Error(name);checks.push(name);console.log('PASS',name);}
await page.reload();await page.waitForFunction(()=>!!state.home);
check(await page.evaluate(async()=>{const r=await(await fetch('/__qa/info')).json();return r.isolated&&r.provider==='synthetic';}),'isolated progress and synthetic provider');
await page.cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
await page.click('loc=role:button[name="句子"]');
console.log(await page.snapshot());
check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'home fits phone width');
await page.evaluate(()=>{
 const Original=window.AudioContext;
 window.AudioContext=new Proxy(Original,{construct(Target,args){const context=Reflect.construct(Target,args);window.qaContext=context;return context;}});
 navigator.mediaDevices.getUserMedia=async()=>{
   const context=window.qaContext;const oscillator=context.createOscillator();const gain=context.createGain();const destination=context.createMediaStreamDestination();
   oscillator.frequency.value=220;gain.gain.value=.15;oscillator.connect(gain);gain.connect(destination);oscillator.start();window.qaGain=gain;
   return destination.stream;
 };
});
await page.mouse.wheel(0,350,{label:'查看句子语速选项'});
await page.click('loc=css:#pane-sentence [data-reading-speed-picker] button[aria-pressed="true"]');
await page.click('#sentence-start-btn');
await page.waitForFunction(()=>['previewing','playing','following'].includes(state.sentenceMode),undefined,{timeout:20000});
check(await page.evaluate(()=>reading.enabled),'native start gesture activates recording pipeline');
check(await page.evaluate(()=>sentenceSpeed===.85&&els.sentencePlayer.preservesPitch&&els.sentencePlayer.playbackRate===.85),'default 0.85 speed preserves pitch');
await page.evaluate(()=>{state.sentenceSession.items=state.sentenceSession.items.slice(0,2);});
await page.waitForFunction(()=>state.sentenceMode==='following',undefined,{timeout:30000});
check(await page.evaluate(()=>state.uiSentenceFollowTotalMs>=Math.min(59000,Math.max(7000,currentSentenceItem().clip_duration/.85*1700+2000))-1),'learner time follows slow speed with extra room');
await page.screenshot({path:out+'/following-390.png'});
check(await page.evaluate(()=>!document.getElementById('reading-done-sentence').disabled),'early finish available only while recording');
// Wait for real generated samples, not a fixed timing assumption.
await page.evaluate(()=>{window.qaFirstStart=qaContext.currentTime;});
await page.waitForFunction(()=>qaContext.currentTime-qaFirstStart>.4);
await page.evaluate(()=>{window.qaEndedAt=performance.now();});
await page.click('#reading-done-sentence');
await page.waitForFunction(()=>state.sentencePass===2&&state.sentenceMode==='playing');
check(await page.evaluate(()=>performance.now()-qaEndedAt<3500),'next pass starts before four-second provider reply');
check(await page.evaluate(()=>!document.getElementById('assessment-sentence').textContent.includes('分')),'no score interruption during practice');
// Native audio events are accelerated only after the first real playback.
async function recordTurn(){
  await page.evaluate(()=>{if(state.sentenceMode==='previewing'){clearTimeout(state.sentenceFollowTimeout);setSentenceMode('playing');}if(state.sentenceMode==='playing'){els.sentencePlayer.pause();els.sentencePlayer.dispatchEvent(new Event('ended'));}});
  await page.waitForFunction(()=>state.sentenceMode==='following');
  await page.evaluate(()=>{window.qaTurnStart=qaContext.currentTime;});
  await page.waitForFunction(()=>qaContext.currentTime-qaTurnStart>.4);
  await page.click('#reading-done-sentence');
}
await recordTurn();await page.waitForFunction(()=>state.sentenceIndex===1);
// Second item is made silent to verify no automatic completion or charge.
await page.evaluate(()=>qaGain.gain.value=0);
await recordTurn();await page.waitForSelector('#assessment-sentence button');
check(await page.evaluate(()=>state.sentenceMode==='finishing'&&state.sentenceCompleted===1),'silence does not complete or auto-advance');
await page.click('loc=role:button[name="再读一次"]');
await page.evaluate(()=>qaGain.gain.value=.15);
await recordTurn();await page.waitForFunction(()=>state.sentencePass===2&&state.sentenceMode==='playing');
await recordTurn();await page.waitForFunction(()=>state.sentenceMode==='completed');
await page.waitForSelector('.reading-summary');
check(await page.evaluate(()=>!!document.querySelector('.reading-summary')&&state.sentenceCompleted===2),'completion contains asynchronous reading summary');
await page.waitForFunction(()=>!document.querySelector('.reading-summary [role=status]').textContent.includes('整理中'),undefined,{timeout:30000});
check(await page.evaluate(()=>!els.completeBody.textContent.includes('朗读评分')),'completion does not invent overall nasal score');
await page.screenshot({path:out+'/summary-390.png'});
check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'summary fits phone width');
await page.click('loc=role:button[name="返回首页"]');
await page.click('loc=role:button[name="句子"]');
await page.mouse.wheel(0,350,{label:'查看朗读回顾入口'});
await page.click('#reading-review-btn');
await page.waitForFunction(()=>!document.querySelector('#complete-body').textContent.includes('正在读取'));
check(await page.evaluate(()=>els.completeBody.textContent.includes('最近的朗读评测')),'durable reading history is reachable from sentence home');
await fs.writeFile(out+'/ui-report.json',JSON.stringify({checks,provider:'synthetic',microphone:'generated tone; no human recording'},null,2));
console.log(await page.snapshot());
