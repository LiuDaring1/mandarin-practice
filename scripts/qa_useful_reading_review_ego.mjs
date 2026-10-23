// Uses a caller-created Ego space, fake tone microphone, isolated 8778 progress.
const spaceId=Number(globalThis.PTH_QA_CONFIG?.spaceId);if(!spaceId)throw new Error('Provide PTH_QA_CONFIG with the existing TaskSpace id');
const task=await taskSpace(spaceId),page=task.page('p2');
const fs=await import('node:fs/promises'),out=globalThis.PTH_QA_CONFIG.outputDir;await fs.mkdir(out,{recursive:true});
const checks=[];function check(ok,name){if(!ok)throw new Error(name);checks.push(name);console.log('PASS',name);}
await page.reload();await page.waitForFunction(()=>!!state.home);
await page.cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
check(await page.evaluate(async()=>{const i=await(await fetch('/__qa/info')).json();return i.isolated&&i.provider==='synthetic';}),'isolated synthetic provider');
await page.evaluate(()=>{
 const Original=window.AudioContext;window.AudioContext=new Proxy(Original,{construct(T,args){const c=Reflect.construct(T,args);window.qaContext=c;return c;}});
 navigator.mediaDevices.getUserMedia=async()=>{const c=qaContext,o=c.createOscillator(),g=c.createGain(),d=c.createMediaStreamDestination();o.frequency.value=220;g.gain.value=.15;o.connect(g);g.connect(d);o.start();return d.stream;};
});
async function control(completion){await page.evaluate(async(completion)=>await fetch('/__qa/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({completion,nasal_ready:false,delay:.2})}),completion);}
async function wordRound(reuse){
 await page.mouse.wheel(0,320,{label:'查看开始训练按钮'});await page.click('#start-btn');
 await page.waitForFunction(()=>!!state.session?.items?.length,undefined,{timeout:20000});
 await page.evaluate(reuse=>{if(reuse){state.session.items=[window.qaItem];playItem(0);}else{state.session.items=state.session.items.slice(0,1);window.qaItem=state.session.items[0];}},reuse);
 await page.waitForFunction(()=>state.mode==='waiting_follow',undefined,{timeout:15000});
 await page.evaluate(()=>window.qaStart=qaContext.currentTime);await page.waitForFunction(()=>qaContext.currentTime-qaStart>.4);
 await page.click('#reading-done-word');await page.waitForFunction(()=>state.mode==='completed');
 await page.waitForFunction(async()=>{const r=await(await fetch('/api/reading/review')).json();return r.sessions.length&&!r.sessions[0].pending;});
 // UI polling follows accepted background completion.
 await page.waitForFunction(()=>!document.querySelector('.reading-summary')||document.querySelector('.reading-summary').hidden||document.querySelector('.reading-summary').innerText.includes('完整'));
}
await control(100);await wordRound(false);
check(await page.evaluate(()=>document.querySelector('.reading-summary').hidden),'empty report hidden after a complete reading');
const forbidden=/已评测|音素细节|诊断仍在验证|目标鼻韵母反馈|正在整理后台|不生成自动错音|建议复练 0/;
check(!forbidden.test(await page.evaluate(()=>document.body.innerText)),'completion contains no engineering statuses');
await page.screenshot({path:out+'/complete-clean-390.png'});
await page.click('loc=role:button[name="返回首页"]');await page.click('loc=role:button[name="句子"]');
check(await page.evaluate(()=>document.getElementById('reading-review-btn').hidden&&getComputedStyle(document.getElementById('reading-review-btn')).display==='none'),'no empty review entry on home');
await page.click('loc=role:button[name="字词"]');await control(50);await wordRound(true);
await page.waitForFunction(()=>!document.querySelector('.reading-summary').hidden,undefined,{timeout:10000});
check(await page.evaluate(()=>document.querySelector('.reading-summary').innerText.includes(qaItem.word)),'incomplete reading names the actual content');
check(!forbidden.test(await page.evaluate(()=>document.body.innerText)),'actionable recap also hides engineering counts');
await page.click('loc=role:button[name="返回首页"]');await page.click('loc=role:button[name="句子"]');
await page.waitForFunction(()=>!document.getElementById('reading-review-btn').hidden);
await page.mouse.wheel(0,350,{label:'查看朗读回顾'});await page.click('#reading-review-btn');
check(await page.evaluate(()=>els.completeBody.innerText.includes(qaItem.word)&&!els.completeBody.innerText.includes('最近的朗读评测')),'history shows practice content instead of job list');
await page.click('loc=role:button[name="返回首页"]');await page.click('loc=role:button[name="字词"]');await control(100);await wordRound(true);
await page.click('loc=role:button[name="返回首页"]');await page.waitForFunction(()=>document.getElementById('reading-review-btn').hidden);
check(await page.evaluate(async()=>(await(await fetch('/api/reading/review')).json()).retry_items.length===0),'later complete reading clears retry suggestion');
await fs.writeFile(out+'/ui-report.json',JSON.stringify({checks,microphone:'generated tone',provider:'synthetic',origin:'isolated 8778'},null,2));
console.log(await page.snapshot());
