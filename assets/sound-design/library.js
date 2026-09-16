const $ = id => document.getElementById(id);
const quick = [2, 7, 5, 23, 11, 49];
const audio = new Audio();
audio.preload = 'none';
let intent = 0, current = null, pendingFinish = null, timer = 0;
let samples = [], history = [];
function status(text) { $('status').textContent = text; }
function markSample(id) {
  current = id;
  for (const button of document.querySelectorAll('[data-sample]')) button.setAttribute('aria-pressed',String(Number(button.dataset.sample)===id));
}
function stop(message='所有试听已停止') {
  ++intent;
  clearTimeout(timer);
  audio.pause(); audio.removeAttribute('src'); audio.load();
  pendingFinish?.(false); pendingFinish=null;
  markSample(null);
  $('reel').setAttribute('aria-pressed','false'); $('cute-reel').setAttribute('aria-pressed','false');
  status(message);
}
function volume() {audio.volume=Number($('volume').value)/100; $('volume-value').value=$('volume').value+'%';}
$('volume').addEventListener('input',volume); volume();
$('stop').addEventListener('click',()=>stop());
document.addEventListener('keydown',event=>{if(event.key==='Escape')stop();});
document.addEventListener('visibilitychange',()=>{if(document.hidden)stop('页面已离开 · 试听停止');});
window.addEventListener('pagehide',()=>stop());
function playSample(id,own) {
  return new Promise(resolve=>{
    if(own!==intent)return resolve(false);
    const spec=samples.find(s=>s.number===id);
    if(!spec){status('这个样本未找到');return resolve(false);}
    let settled=false;
    const finish=ok=>{if(settled)return;settled=true;clearTimeout(timer);if(pendingFinish===finish)pendingFinish=null;resolve(ok);};
    pendingFinish=finish;
    audio.onended=()=>{markSample(null);history.push({type:'ended',id});finish(true);};
    audio.onerror=()=>{if(own===intent){markSample(null);status('本地样本加载失败，可重新点击');}finish(false);};
    audio.src=spec.url;audio.currentTime=0;markSample(id);status(`${spec.label ? 'Cute UI · '+spec.label : 'Dustyroom · 原音 '+String(id).padStart(2,'0')} · ${spec.duration.toFixed(2)} 秒`);
    // A time limit also resolves the sequence if a media backend never emits error/ended.
    timer=setTimeout(()=>{if(own===intent){audio.pause();markSample(null);status('本次播放超时，请重试');}finish(false);},12000);
    audio.play().then(()=>{if(own===intent)history.push({type:'played',id});}).catch(()=>{
      if(own===intent){markSample(null);status('未能播放，请再点击一次试听');}finish(false);
    });
  });
}
function buttonFor(spec) {
  const button=document.createElement('button');button.type='button';button.className='sample';button.dataset.sample=spec.number;button.setAttribute('aria-pressed','false');button.setAttribute('aria-label',spec.label ? `试听 R4orce ${spec.source_number} ${spec.label}` : `试听 Dustyroom 原音 ${String(spec.number).padStart(2,'0')}`);
  const name=document.createElement('b');name.textContent='▶ '+(spec.label || String(spec.number).padStart(2,'0'));const duration=document.createElement('small');duration.textContent=(spec.source_number ? String(spec.source_number).padStart(2,'0')+' · ' : '')+spec.duration.toFixed(2)+' 秒';button.append(name,duration);
  button.addEventListener('click',async()=>{stop();const own=intent;const ok=await playSample(spec.number,own);if(ok&&own===intent)status(`${spec.label || '原音 '+String(spec.number).padStart(2,'0')} 播放完毕`);});
  return button;
}
$('reel').disabled=true; $('cute-reel').disabled=true;
try {
  const response=await fetch('/library-manifest.json');if(!response.ok)throw Error(response.status);
  const manifest=await response.json();samples=[...manifest.samples,...manifest.extra_samples];
  for (const id of quick) $('quick-samples').append(buttonFor(samples.find(s=>s.number===id)));
  for (const spec of manifest.samples) $('all-samples').append(buttonFor(spec));
  for (const id of [103,106,105,111,121,125,126,130]) $('cute-samples').append(buttonFor(samples.find(s=>s.number===id)));
  for (const spec of manifest.extra_samples) $('cute-all').append(buttonFor(spec));
  $('reel').disabled=false; $('cute-reel').disabled=false;
} catch {status('素材清单加载失败，请刷新页面后重试');}
async function playSequence(ids,button){
  stop();const own=intent;button.setAttribute('aria-pressed','true');
  for (const id of ids) {
    if(own!==intent)return;
    if(!await playSample(id,own)){if(own===intent)button.setAttribute('aria-pressed','false');return;}
    const continued=await new Promise(resolve=>{pendingFinish=resolve;timer=setTimeout(()=>{pendingFinish=null;resolve(true);},450);});
    if(!continued||own!==intent)return;
  }
  button.setAttribute('aria-pressed','false');status('6 个原音播放完毕 · 可以按编号重听');
}
$('reel').addEventListener('click',()=>playSequence(quick,$('reel')));
$('cute-reel').addEventListener('click',()=>playSequence([103,106,105,121,125,130],$('cute-reel')));
window.libraryLab={stop,audio,getState:()=>({current,playing:!audio.paused,ready:samples.length,embeds:document.querySelectorAll('.embed-slot iframe').length,history:[...history],intent})};
