// Run in an existing Ego TaskSpace against disposable serve_practice_qa.py only.
const cfg=globalThis.PTH_QA_CONFIG;
if(!cfg?.spaceId || !cfg?.outputDir)throw new Error('Provide PTH_QA_CONFIG');
const task=await taskSpace(cfg.spaceId),page=task.page('p1');
const fs=await import('node:fs/promises');await fs.mkdir(cfg.outputDir,{recursive:true});
const checks=[];function check(ok,name){if(!ok)throw new Error(name);checks.push(name);console.log('PASS',name);}
await page.goto('http://127.0.0.1:8779');
await page.waitForFunction(()=>state.home && !els.startBtn.disabled,undefined,{timeout:20000});
check(await page.evaluate(async()=>{const i=await(await fetch('/__qa/info')).json();return i.isolated&&i.provider==='local_only';}),'disposable local-only backend');
await page.evaluate(()=>{
 localStorage.setItem('pth-reading-speed-v1','.75'); // Old preference must not slow the new player.
 const raw=window.fetch;window.qaRequests=[];window.fetch=(...args)=>{qaRequests.push(String(args[0]));return raw(...args);};
 const Original=window.AudioContext;window.AudioContext=new Proxy(Original,{construct(T,args){const c=Reflect.construct(T,args);window.qaContext=c;return c;}});
 navigator.mediaDevices.getUserMedia=async()=>{const c=qaContext,o=c.createOscillator(),g=c.createGain(),d=c.createMediaStreamDestination();o.frequency.value=220;g.gain.value=.15;window.qaGain=g;o.connect(g);g.connect(d);o.start();return d.stream;};
});
check(await page.evaluate(()=>state.duration===3 && JSON.stringify(state.home.durations)==='[3,5]'),'word 3/5-minute choices default to 3');
await page.click('#tab-sentence');
check(await page.evaluate(()=>state.sentenceCount===5&&document.querySelectorAll('#sentence-filter-options button').length===2&&document.querySelectorAll('[data-reading-speed-picker]').length===0&&document.getElementById('reading-review-btn').hidden),'sentence 5/10 choices, two filters, no speed/review controls');
check(await page.evaluate(async()=>{const s=await(await fetch('/api/sentence/home')).json();return s.source_counts.news===0&&s.source_counts.literature===582;}),'formal sentence pool contains only 582 literature clips');
await page.screenshot({path:cfg.outputDir+'/home-390.png'});
await page.click('#sentence-start-btn');
await page.waitForFunction(()=>state.sentenceMode==='playing',undefined,{timeout:20000});
check(await page.evaluate(()=>els.sentencePlayer.playbackRate===1&&state.sentenceSession.items.length===5&&state.sentenceSession.items.every(i=>i.genre==='literature')),'original-speed literature round ignores old slow preference');
// Seek reference playback only, so this is a flow test rather than listening QA.
async function follow(){
 await page.waitForFunction(()=>['playing','following'].includes(state.sentenceMode),undefined,{timeout:15000});
 await page.evaluate(()=>{if(state.sentenceMode==='playing'&&Number.isFinite(els.sentencePlayer.duration))els.sentencePlayer.currentTime=Math.max(0,els.sentencePlayer.duration-.03);});
 await page.waitForFunction(()=>state.sentenceMode==='following',undefined,{timeout:20000});
}
async function voice(){await page.evaluate(()=>window.qaTime=qaContext.currentTime);await page.waitForFunction(()=>qaContext.currentTime-qaTime>.45);}
await follow();await page.click('#sentence-pause-btn');
check(await page.evaluate(()=>state.sentenceMode==='paused'&&els.sentencePauseLabel.textContent==='重新跟读'&&document.getElementById('reading-done-sentence').disabled),'paused recording clearly offers restart, done is disabled');
for(const width of [320,390,430]){
 await page.cdp('Emulation.setDeviceMetricsOverride',{width,height:844,deviceScaleFactor:1,mobile:true});
 check(await page.evaluate(()=>Array.from(document.querySelectorAll('#view-sentence .control-btn')).every(b=>{
 const r=b.getBoundingClientRect(),i=b.querySelector('.ctl-icon')?.getBoundingClientRect(),l=b.querySelector('.ctl-label')?.getBoundingClientRect();
 return r.left>=0&&r.right<=innerWidth&&(!i||Math.abs(i.left+i.width/2-l.left-l.width/2)<1);
 })),`centered controls fit ${width}px`);
 await page.screenshot({path:cfg.outputDir+`/paused-${width}.png`});
}
await page.cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
await page.click('#sentence-pause-btn');
check(await page.evaluate(()=>state.sentenceMode==='following'&&state.sentenceFollowDeadline-performance.now()>state.uiSentenceFollowTotalMs-1500),'restart opens a fresh recording window');
for(let turn=0;turn<10;turn++){
 if(turn)await follow();
 await voice();
 await page.click('#reading-done-sentence');
 await page.waitForFunction(()=>state.sentenceMode!=='finishing');
}
await page.waitForFunction(()=>state.sentenceMode==='completed');
check(await page.evaluate(()=>state.sentenceCompleted===5&&els.completeBody.innerText.includes('300')&&!document.querySelector('.reading-summary')),'five voiced sentences settle 300 beads without recap');
check(await page.evaluate(()=>!qaRequests.some(u=>u.includes('/api/reading/attempts/')||u.includes('/api/assessment/word/')||u.includes('/api/assessment/sentence/'))),'no audio upload requests during practice');
await page.screenshot({path:cfg.outputDir+'/completion-390.png'});
// Silent and denied microphone never count as completed reading.
await page.evaluate(()=>resetToHome());await page.click('#tab-words');await page.click('#start-btn');
await page.waitForFunction(()=>!!state.session?.items?.length);
await page.evaluate(()=>{state.session.items=state.session.items.slice(0,1);qaGain.gain.value=0;});
await page.waitForFunction(()=>state.mode==='waiting_follow',undefined,{timeout:15000});
await voice();await page.click('#reading-done-word');
await page.waitForFunction(()=>document.getElementById('assessment-word').innerText.includes('没有检测到'));
check(await page.evaluate(()=>state.completedItems===0),'silence requires retry or skip');
await page.click('loc=role:button[name="跳过这遍"]');await page.waitForFunction(()=>state.mode==='completed');
check(await page.evaluate(()=>state.completedItems===0),'skipping silence earns no completed item');
await page.evaluate(()=>{resetToHome();navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('denied','NotAllowedError');};});
await page.click('#start-btn');await page.waitForFunction(()=>!!state.session?.items?.length);
await page.evaluate(()=>{state.session.items=state.session.items.slice(0,1);});
await page.waitForFunction(()=>state.mode==='waiting_follow',undefined,{timeout:15000});await page.click('#reading-done-word');
await page.waitForFunction(()=>state.mode==='completed');
check(await page.evaluate(()=>state.completedItems===0&&!completedToday('word')),'denied microphone does not complete reading or daily trio');
check(await page.evaluate(()=>{
 const base={type:'word',dayKey:todayKey(),exitEarly:false};
 return !isValidSession({...base,ratio:0})&&isValidSession(base)&&isValidSession({...base,ratio:.2})
   &&sessionCompletionRatio({...base,ratio:.995})<1;
}),'explicit zero is not an effective training day; old missing ratios remain compatible');
await fs.writeFile(cfg.outputDir+'/ui-report.json',JSON.stringify({checks,microphone:'generated tone / silence / simulated denial',provider:'local_only',referencePlayback:'seeked for flow QA; not listening acceptance'},null,2));
console.log(await page.snapshot());
