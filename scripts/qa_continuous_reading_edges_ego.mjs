// Additional browser state/race checks in the same TaskSpace and isolated origin.
const spaceId=Number(process.env.PTH_QA_SPACE);if(!spaceId)throw new Error('Set PTH_QA_SPACE to the existing browser TaskSpace id');
const task=await taskSpace(spaceId),page=task.page('p1');
const fs=await import('node:fs/promises');
const file=process.cwd()+'/handoff/continuous-reading-2026-10-23/ui-report.json';
const checks=[];function check(ok,name){if(!ok)throw new Error(name);checks.push(name);console.log('PASS',name);}
await page.reload();await page.waitForFunction(()=>!!state.home);
await page.click('loc=role:button[name="句子"]');
await page.mouse.wheel(0,320,{label:'查看慢速选项'});
await page.click('loc=css:#pane-sentence [data-reading-speed-picker] button:nth-child(1)');
check(await page.evaluate(()=>sentenceSpeed===.75),'0.75 speed selectable');
await page.reload();await page.waitForFunction(()=>!!state.home);
check(await page.evaluate(()=>sentenceSpeed===.75),'speed choice survives reload');
await page.evaluate(()=>{
 const Original=window.AudioContext;window.AudioContext=new Proxy(Original,{construct(T,args){const c=Reflect.construct(T,args);window.qaContext=c;return c;}});
 navigator.mediaDevices.getUserMedia=async()=>{const c=qaContext,o=c.createOscillator(),g=c.createGain(),d=c.createMediaStreamDestination();o.frequency.value=220;g.gain.value=.15;o.connect(g);g.connect(d);o.start();window.qaGain=g;return d.stream;};
});
await page.click('loc=role:button[name="句子"]');await page.click('#sentence-start-btn');
await page.waitForFunction(()=>state.sentenceSession?.items?.length>0);
await page.evaluate(()=>{
 const news=state.sentenceSession.items.find(i=>i.genre==='news');if(!news)throw new Error('news absent');
 state.sentenceSession.items=[news];playSentence(0);
});
await page.waitForFunction(()=>state.sentenceMode==='previewing');
check(await page.evaluate(()=>els.sentencePlayer.playbackRate===.75&&currentSentenceItem().genre==='news'),'actual news uses 0.75 speed');
await page.click('#sentence-pause-btn');
check(await page.evaluate(()=>state.sentenceMode==='paused'),'preview can pause safely');
await page.click('#sentence-pause-btn');
check(await page.evaluate(()=>state.sentenceMode==='playing'&&els.sentencePlayer.playbackRate===.75),'preview resumes at selected speed');
await page.evaluate(()=>{els.sentencePlayer.pause();els.sentencePlayer.dispatchEvent(new Event('ended'));});
await page.waitForFunction(()=>state.sentenceMode==='following');
await page.click('#sentence-pause-btn');
check(await page.evaluate(()=>state.sentenceMode==='paused'&&document.getElementById('reading-done-sentence').disabled),'pause disables early-finish action');
await page.click('#sentence-pause-btn');
await page.evaluate(()=>{window.qaT=qaContext.currentTime;});await page.waitForFunction(()=>qaContext.currentTime-qaT>.4);
await page.evaluate(async()=>await fetch('/__qa/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:'unavailable',delay:3})}));
await page.click('#reading-done-sentence');
await page.waitForFunction(()=>state.sentencePass===2&&state.sentenceMode==='playing');
await page.evaluate(()=>{els.sentencePlayer.pause();els.sentencePlayer.dispatchEvent(new Event('ended'));window.qaT=qaContext.currentTime;});
await page.waitForFunction(()=>qaContext.currentTime-qaT>.4);
await page.click('#reading-done-sentence');await page.waitForFunction(()=>state.sentenceMode==='completed');
check(await page.evaluate(()=>state.sentenceCompleted===1),'provider failure does not interrupt locally voiced practice');
await page.waitForFunction(()=>document.querySelector('.reading-summary')?.textContent.includes('未能评测'),undefined,{timeout:15000});
check(await page.evaluate(()=>document.querySelector('.reading-summary').textContent.includes('不记零分')),'failure is reported without zero scores');
await page.click('loc=role:button[name="返回首页"]');await page.click('loc=role:button[name="句子"]');
await page.evaluate(()=>navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('QA denied','NotAllowedError');});
await page.click('#sentence-start-btn');await page.waitForFunction(()=>!!state.sentenceSession?.items?.length);
check(await page.evaluate(()=>!reading.enabled&&reading.required),'denied permission retains recording requirement');
await page.evaluate(()=>{state.sentenceSession.items=state.sentenceSession.items.slice(0,1);clearTimeout(state.sentenceFollowTimeout);setSentenceMode('playing');els.sentencePlayer.pause();els.sentencePlayer.dispatchEvent(new Event('ended'));});
await page.click('#reading-done-sentence');await page.waitForFunction(()=>state.sentencePass===2);
await page.evaluate(()=>{els.sentencePlayer.pause();els.sentencePlayer.dispatchEvent(new Event('ended'));});
await page.click('#reading-done-sentence');await page.waitForFunction(()=>state.sentenceMode==='completed');
check(await page.evaluate(()=>state.sentenceCompleted===0),'listening only earns no reading completion');
await page.click('loc=role:button[name="返回首页"]');
// New run invalidates old rendering, but accepted server jobs continue.
check(await page.evaluate(()=>qaContext.state==='closed'),'microphone context released after completion');
for(const width of [360,430,1200]){
 await page.cdp('Emulation.setDeviceMetricsOverride',{width,height:844,deviceScaleFactor:1,mobile:width<500});
 check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`home width ${width}`);
}
const report=JSON.parse(await fs.readFile(file,'utf8'));report.checks.push(...checks);await fs.writeFile(file,JSON.stringify(report,null,2));
console.log(await page.snapshot());
