// Explicit isolated UI acceptance; uses a fake microphone fed by an existing reference.
const task=await taskSpace(24), page=task.page('p3');
const fs=await import('node:fs/promises');
const root='/Volumes/语苗计划/桌面整理2026-10-01/01_语音项目/普通话语音系统/普通话语音系统-zcode';
const out=root+'/handoff/news-assessment-2026-10-22';
await fs.mkdir(out,{recursive:true});
const pointer=JSON.parse(await fs.readFile(root+'/data/derived/voice-conversion/active.json','utf8'));
const manifest=JSON.parse(await fs.readFile(root+'/data/'+pointer.voices['news-female'].manifest,'utf8'));
const audioBase64=(await fs.readFile(manifest.clips['t1-05301'].replacement)).toString('base64');
const checks=[];
function check(value,label){if(!value)throw new Error(label);checks.push(label);console.log('PASS',label);}
await page.reload();await page.waitForFunction(()=>!!state.home);
check(await page.evaluate(async()=>(await(await fetch('/__qa/info')).json()).isolated),'disposable progress directory');
await page.cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
await page.screenshot({path:out+'/home-390.png'});
check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'home has no horizontal overflow');
await page.cdp('Page.bringToFront');
await page.evaluate(()=>{
  window.qaAllContexts=[];
  const Original=window.AudioContext;
  window.AudioContext=new Proxy(Original,{construct(Target,args){if(window.qaSharedContext&&qaSharedContext.state!=='closed')return qaSharedContext;const c=Reflect.construct(Target,args);qaSharedContext=c;qaAllContexts.push(c);return c;}});
  for(const name of ['unlock','play','stop','stopBus','settlement'])window.appSfx[name]=()=>{};
  window.appSfx.beginTeaching=()=>()=>{};
  const button=document.createElement('button');button.id='qa-activate-audio';button.textContent='录音验收';button.style='position:fixed;top:0;left:0;z-index:999999';
  button.onclick=()=>{if(window.qaBeginRecording){const begin=qaBeginRecording;qaBeginRecording=null;begin();}qaAllContexts.filter(c=>c.state!=='closed').forEach(c=>c.resume().catch(()=>{}));};document.body.append(button);
});
async function finishPreparation(){
  await page.click('#qa-activate-audio');
  for(let i=0;i<5;i++){
    await page.waitForFunction(()=>window.qaPrepareSettled||qaAllContexts.some(c=>c.state==='suspended'),null,{timeout:10000});
    if(await page.evaluate(()=>window.qaPrepareSettled))break;
    await page.click('#qa-activate-audio');
  }
  await page.waitForFunction(()=>window.qaPrepareSettled,null,{timeout:12000});
  check(await page.evaluate(()=>window.qaPrepared),'fake microphone audio contexts activated through native clicks');
}
await page.evaluate(async(bytes)=>{
  window.qaInputAudio=Uint8Array.from(atob(bytes),c=>c.charCodeAt(0)).buffer;
  window.qaOriginalMicrophone=navigator.mediaDevices.getUserMedia;
  window.qaAudioContexts=[];
  navigator.mediaDevices.getUserMedia=async()=>{
    const context=new AudioContext();context.resume().catch(()=>{});qaAudioContexts.push(context);
    const destination=context.createMediaStreamDestination(), source=context.createBufferSource();
    const audio=window.qaInputAudio;
    const view=new DataView(audio);let offset=12,rate=16000,start=0,size=0;
    const tag=at=>String.fromCharCode(...new Uint8Array(audio,at,4));
    while(offset+8<audio.byteLength){const length=view.getUint32(offset+4,true);if(tag(offset)==='fmt ')rate=view.getUint32(offset+12,true);if(tag(offset)==='data'){start=offset+8;size=length;break;}offset+=8+length+(length%2);}
    const samples=new Float32Array(size/2);samples.forEach((_,i)=>{samples[i]=view.getInt16(start+i*2,true)/32768;});
    source.buffer=context.createBuffer(1,samples.length,rate);source.buffer.copyToChannel(samples,0);source.connect(destination);window.qaMicSource=source;
    return destination.stream;
  };
  setView('training');
  window.qaBeginRecording=()=>{window.qaPrepareSettled=false;window.qaPrepared=false;window.qaSharedContext=null;
  reading.prepare().then(value=>{window.qaPrepared=value;window.qaPrepareSettled=true;if(value){reading.start('word');qaMicSource.start();window.qaRecordingStarted=performance.now();}});};
},audioBase64);
await finishPreparation();
check(await page.evaluate(()=>qaPrepared&&reading.enabled&&reading.required),'worklet microphone prepared');
await page.waitForFunction(()=>performance.now()-qaRecordingStarted>1600);
await page.evaluate(()=>{window.qaResult=null;reading.grade('word','t1-05301',()=>{}).then(r=>window.qaResult=r);});
await page.waitForFunction(()=>document.querySelector('#assessment-word')?.textContent.includes('评分'),null,{timeout:35000});
await page.screenshot({path:out+'/assessment-word-390.png'});
check(await page.evaluate(()=>/朗读评分 \d+ 分/.test(document.querySelector('#assessment-word').textContent)),'recorded PCM resampled and scored by Tencent');
await page.waitForFunction(()=>!!window.qaResult,null,{timeout:8000});
check(await page.evaluate(()=>qaResult.advance&&qaResult.complete),'scored speech counts without a score threshold');
await page.evaluate(async()=>{
  await reading.close();qaAudioContexts.filter(c=>c.state!=='closed').forEach(c=>c.close());
  navigator.mediaDevices.getUserMedia=async()=>{
    const context=new AudioContext();context.resume().catch(()=>{});qaAudioContexts=[context];
    return context.createMediaStreamDestination().stream;
  };
  window.qaBeginRecording=()=>{window.qaPrepareSettled=false;window.qaPrepared=false;window.qaSharedContext=null;
  reading.prepare().then(value=>{qaPrepared=value;qaPrepareSettled=true;if(value){reading.start('word');window.qaRecordingStarted=performance.now();}});};
});
await finishPreparation();
await page.waitForFunction(()=>performance.now()-qaRecordingStarted>800);
await page.evaluate(()=>{window.qaSilentResult=null;reading.grade('word','t1-05301',()=>{}).then(r=>window.qaSilentResult=r);});
await page.waitForFunction(()=>document.querySelector('#assessment-word')?.textContent.includes('没有检测到'));
check(await page.evaluate(()=>qaSilentResult===null),'silence waits for retry or skip');
await page.screenshot({path:out+'/assessment-silence-390.png'});
await page.click('#assessment-word button:last-child');
await page.waitForFunction(()=>!!qaSilentResult);
check(await page.evaluate(()=>qaSilentResult.advance&&!qaSilentResult.complete),'silence skipped without completion credit');
await page.evaluate(async()=>{
  await reading.close();qaAudioContexts.filter(c=>c.state!=='closed').forEach(c=>c.close());
  navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('denied','NotAllowedError');};
  await reading.prepare();window.qaDenied=await reading.grade('word','t1-05301',()=>{});
});
check(await page.evaluate(()=>reading.required&&!qaDenied.complete),'denied microphone cannot earn reading credit');
await page.evaluate(async()=>{await reading.close();resetToHome();document.querySelector('[data-voice="news-female"]').click();await startLibraryPractice();
  window.qaPlayCount=0;discrimAudio.play=()=>{qaPlayCount++;return Promise.resolve();};
  const item=currentDiscrimItem();window.qaIndex=state.discrimIndex;
  applyDiscrimFeedback({all_correct:false,results:item.points.map(p=>({...p,correct:false}))});
  window.qaFeedbackAt=performance.now();
});
await page.waitForFunction(()=>performance.now()-qaFeedbackAt>850);
check(await page.evaluate(()=>state.discrimIndex===qaIndex&&state.discrimMode==='feedback'&&qaPlayCount===1),'wrong answer plays whole word once and waits past 700ms');
check(await page.evaluate(()=>discrimAudio.src.includes('voice=news-female')),'wrong-answer audio inherits female selection');
await page.screenshot({path:out+'/wrong-answer-390.png'});
await page.evaluate(()=>discrimAudio.onended());
await page.waitForFunction(()=>state.discrimIndex===qaIndex+1);
check(await page.evaluate(()=>state.discrimIndex===qaIndex+1),'advance once after reference ends');
await page.evaluate(()=>{const item=currentDiscrimItem();window.qaIndex=state.discrimIndex;
  applyDiscrimFeedback({all_correct:true,results:item.points.map(p=>({...p,correct:true}))});});
await page.waitForFunction(()=>state.discrimIndex===qaIndex+1);
check(await page.evaluate(()=>qaPlayCount===1),'correct answer does not play reference');
await page.evaluate(()=>{document.querySelector('[data-voice="news-male"]').click();
  const item=currentDiscrimItem();window.qaIndex=state.discrimIndex;
  applyDiscrimFeedback({all_correct:false,results:item.points.map(p=>({...p,correct:false}))});});
check(await page.evaluate(()=>discrimAudio.src.includes('voice=news-male')),'wrong-answer audio inherits male selection');
await page.evaluate(()=>{const stale=discrimAudio.onended;nextDiscrimWord();stale();});
check(await page.evaluate(()=>state.discrimIndex===qaIndex+1),'skip cancels playback and stale callbacks');
await page.evaluate(()=>{resetToHome();navigator.mediaDevices.getUserMedia=qaOriginalMicrophone;});
await fs.writeFile(out+'/ui-report.json',JSON.stringify({checks,isolated:true,recording:'reference audio used as fake microphone; no human recording'},null,2));
console.log('COMPLETE',checks.length);
