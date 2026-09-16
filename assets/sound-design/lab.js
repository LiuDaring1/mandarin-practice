import {SoundManager} from './sound-manager.js';
const $=id=>document.getElementById(id);
const manifest=await fetch('./manifest.json').then(r=>{if(!r.ok)throw Error('声音清单加载失败');return r.json();});
const sound=new SoundManager(manifest);
let style='a', celebration='lift', intent=0, controller=null, holding=false, holdRaf=0, heldAt=0, heldLast=0, beadAccumulator=0, beadCount=0;
const voice=$('voice'); const unbindVoice=sound.bindMedia(voice);
const controls=['quiz','beads10','ceremony','teaching','celebration-reel'];
const isAbort=e=>e?.name==='AbortError';
function sleep(ms,signal) {return new Promise((resolve,reject)=>{
  if(signal?.aborted)return reject(new DOMException('Stopped','AbortError'));
  const stop=()=>{clearTimeout(timer);reject(new DOMException('Stopped','AbortError'));};
  const timer=setTimeout(()=>{signal?.removeEventListener('abort',stop);resolve();},ms);
  signal?.addEventListener('abort',stop,{once:true});
});}
function updateAudio(){const s=sound.snapshot();
  $('audio-state').textContent=s.preferences.muted?'音效已关闭 · 示范音保持可用':s.teaching?'示范播放中 · 音效让路':s.state==='running'?'声音已就绪':s.state==='suspended'?'已暂停 · 点击试听继续':'点击任一试听，开启声音';
  $('audio-dot').classList.toggle('on',s.state==='running'&&!s.preferences.muted);
  $('mute').textContent=s.preferences.muted?'开启音效':'关闭音效';$('mute').setAttribute('aria-pressed',String(s.preferences.muted));
  $('volume').value=Math.round(s.preferences.volume*100);$('volume-value').value=Math.round(s.preferences.volume*100)+'%';
}
sound.onChange=updateAudio;updateAudio();
$('volume').addEventListener('input',e=>sound.setPreferences({volume:Number(e.target.value)/100}));
$('mute').addEventListener('click',()=>sound.setPreferences({muted:!sound.preferences.muted}));
function setStage(title,description,tag='独立模拟',progress=0){
  $('stage-title').textContent=title;$('stage-description').textContent=description;$('stage-tag').textContent=tag;
  $('progress-fill').style.width=Math.min(100,Math.max(0,progress))+'%';
}
function stopHold(){holding=false;cancelAnimationFrame(holdRaf);$('hold').classList.remove('holding');sound.stopBus('bead');}
function cancel(){++intent;controller?.abort();controller=null;stopHold();sound.stopAll();voice.pause();voice.currentTime=0;
  $('bead-board').classList.remove('fusing');controls.forEach(id=>$(id).setAttribute('aria-pressed','false'));}
$('stop').addEventListener('click',()=>{cancel();setStage('停在这里。','所有试听已停止，随时可以重新开始。');$('teaching-state').textContent='示范与计时已停止';});
async function run(id,job){cancel();const own=intent;const ac=new AbortController();controller=ac;
  $(id)?.setAttribute('aria-pressed','true');
  setStage('正在准备试听…','点“全部停止”可以随时结束。','独立模拟',0);
  try{const ready=await sound.unlock();if(own!==intent)return;
    if(!ready){setStage('声音暂时无法播放','可以再次点击试听；文字与模拟仍然独立于训练记录。');return;}
    await job(ac.signal);
  }catch(e){if(!isAbort(e)){setStage('这次试听没有播放成功','请再试一次，或检查本地音频是否可以加载。');sound.record('flow-error',id,{message:String(e)});}}
  finally{if(own===intent){controller=null;$(id)?.setAttribute('aria-pressed','false');}}
}
const celebrationIds=['reward.arrive','day.complete','artwork.complete','series.complete'];
function chosen(id){return celebration==='lift'&&celebrationIds.includes(id)?'a-lift':'a';}
function play(id,options={}){return sound.play(id,{style:chosen(id),...options});}
async function single(id,options={}){cancel();const own=intent;if(await sound.unlock()&&own===intent){
  const s=manifest.sounds.find(s=>s.id===id&&s.style===(options.style||chosen(id)));
  const handle=play(id,{optional:true,...options});
  setStage(s?.label||id,handle.started?(s?.description||''):'本次保持安静 · '+(handle.reason==='teaching'?'示范音优先':'可稍后再次试听'),options.style==='a-lift'?'A · 新版欢庆':options.style==='b'?'B · 软糖气泡':options.style==='legacy'?'原有音色':'A · 首轮原版');}}
const compare=[['ui.confirm','轻点'],['answer.correct','答对'],['bead.place','落珠'],['artwork.complete','完成']];
for(const el of document.querySelectorAll('.compare-buttons'))for(const [id,label]of compare){
  const b=document.createElement('button');b.textContent='▶ '+label;b.dataset.sound=id;b.dataset.style=el.dataset.style;
  b.setAttribute('aria-label',`${el.dataset.style.toUpperCase()} 组 ${label}`);b.onclick=()=>single(id,{style:el.dataset.style});el.append(b);
}
for(const [w,offset]of [...document.querySelectorAll('.waveform')].map((w,i)=>[w,i])){
  for(let i=0;i<45;i++){const bar=document.createElement('i');bar.style.height=(5+29*Math.abs(Math.sin(i*.79+offset))*(.4+.6*Math.sin(Math.PI*i/44)))+'px';w.append(bar);}
}
for(const id of celebrationIds){
  const old=manifest.sounds.find(s=>s.id===id&&s.style==='a');
  const fresh=manifest.sounds.find(s=>s.id===id&&s.style==='a-lift');
  const card=document.createElement('article');card.className='celebration-card';
  card.innerHTML=`<div class="celebration-card-head"><h3>${fresh.label}</h3><span>${(old.duration_ms/1000).toFixed(2)} → ${(fresh.duration_ms/1000).toFixed(2)} 秒</span></div><p>${fresh.description}</p><div class="celebration-buttons"><button data-celebration="${id}" data-version="original" class="small-button">▶ 原版 · 克制</button><button data-celebration="${id}" data-version="lift" class="celebration-play">▶ 新版 · 欢庆</button><a href="${fresh.variants[0]}" download aria-label="下载新版 ${fresh.label}">WAV ↗</a></div>`;
  for(const b of card.querySelectorAll('button'))b.onclick=()=>{
    $('celebration-feedback').textContent=`正在试听${fresh.label} · ${b.dataset.version==='lift'?'新版欢庆':'原版克制'}`;
    single(id,{style:b.dataset.version==='lift'?'a-lift':'a'});
  };
  $('celebration-grid').append(card);
}
document.querySelectorAll('input[name=celebration]').forEach(r=>r.onchange=()=>{
  cancel();celebration=r.value;
  $('style-note').textContent=celebration==='lift'?'A 日常音 + 新版欢庆':'A 日常音 + 原版庆祝';
  $('celebration-feedback').textContent=celebration==='lift'?'新版庆祝已选中 · 日常音沿用 A':'原版庆祝已选中 · 日常音沿用 A';
  setStage('庆祝声音已切换。','下面的答题结算和完成仪式使用刚刚选定的版本。');
});
$('celebration-reel').onclick=()=>run('celebration-reel',async signal=>{
  for(const id of celebrationIds){
    const spec=manifest.sounds.find(s=>s.id===id&&s.style==='a-lift');
    $('celebration-feedback').textContent='正在连听 · '+spec.label;
    play(id,{style:'a-lift'});await sleep(spec.duration_ms+400,signal);
  }
  $('celebration-feedback').textContent='新版四段播放完毕 · 可切回原版比较';
});
const grid=$('sound-grid');
for(const s of manifest.sounds.filter(s=>s.style==='a'&&!celebrationIds.includes(s.id))){
  const card=document.createElement('article');card.className='sound-card';
  card.innerHTML=`<div class="sound-card-header"><h3>${s.label}</h3><button class="play-circle" aria-label="试听 ${s.label}">▶</button></div><p>${s.description}</p><div class="sound-meta"><span>${s.duration_ms<1000?s.duration_ms+' ms':(s.duration_ms/1000).toFixed(2)+' s'}${s.variants.length>1?' · '+s.variants.length+' 个变体':''}</span><a href="${s.variants[0]}" download aria-label="下载 ${s.label} WAV">WAV ↗</a></div>`;
  card.querySelector('button').onclick=()=>single(s.id,{style:'a'});card.querySelector('button').dataset.sound=s.id;
  if(s.variants.length>1){const variants=document.createElement('div');variants.className='variants';s.variants.forEach((file,i)=>{
    const b=document.createElement('button');b.className='variant';b.textContent=i+1;b.setAttribute('aria-label','落珠变体 '+(i+1));b.onclick=()=>single(s.id,{style:'a',variant:i});variants.append(b);
  });card.append(variants);}grid.append(card);
}
$('legacy').onclick=()=>single('bead.legacy',{style:'legacy'});
for(const s of manifest.scenes){const tr=document.createElement('tr');for(const v of [s.scene,s.strategy,s.reason]){const td=document.createElement('td');td.textContent=v;tr.append(td);}$('scene-list').append(tr);}
const cells=[];const colors=['#57b3a2','#f0b16c','#afa0cc'];
for(let i=0;i<144;i++){const cell=document.createElement('i');cell.style.setProperty('--bead',colors[(Math.floor(i/12)+Math.floor((i%12)/4))%3]);$('bead-board').append(cell);cells.push(cell);}
function clearBoard(){beadCount=0;cells.forEach(c=>c.classList.remove('on'));$('bead-board').classList.remove('finished','fusing');}
function place(count=1){if(count<=0)return;const old=beadCount;beadCount+=count;
  for(let i=old;i<beadCount;i++){if(i%144===0)cells.forEach(c=>c.classList.remove('on'));cells[i%144].classList.add('on');}
  play('bead.place');$('bead-count').textContent=`模拟已拼 ${beadCount} 颗 · 松手即停`;
}
function holdFrame(now){if(!holding)return;
  const dt=Math.min(.1,(now-heldLast)/1000);heldLast=now;const t=(now-heldAt)/1000;
  // Same app curve with disposable 1,900 pending beads. Never changes real placement.
  const remaining=Math.max(0,1900-beadCount),rate=8+44*Math.min(1,Math.max(0,t-.32)/2.5)+Math.min(220,Math.max(0,(remaining-200)/12));
  if(t>.32){beadAccumulator+=dt*rate;const n=Math.floor(beadAccumulator);beadAccumulator-=n;place(n);}
  setStage('珠子，一颗颗落稳。','画面按模拟拼入推进，声音限制密度，避免挤成一团。','连续拼入',t*10);
  holdRaf=requestAnimationFrame(holdFrame);
}
function startHeld(){holding=true;heldAt=heldLast=performance.now();beadAccumulator=0;$('hold').classList.add('holding');place(1);holdRaf=requestAnimationFrame(holdFrame);}
let pointerHeld=false,keyHeld=false;
async function beginManual(event){event.preventDefault();if(holding)return;cancel();clearBoard();
  const own=intent;
  if(event.pointerId!==undefined){pointerHeld=true;try{$('hold').setPointerCapture(event.pointerId);}catch{}}
  else keyHeld=true;
  if(await sound.unlock()&&own===intent&&(pointerHeld||keyHeld))startHeld();
}
function endManual(){pointerHeld=keyHeld=false;stopHold();}
$('hold').addEventListener('pointerdown',e=>{if(e.button===0)beginManual(e);});
for(const e of ['pointerup','pointercancel','lostpointercapture','blur'])$('hold').addEventListener(e,endManual);
$('hold').addEventListener('keydown',e=>{if([' ','Enter'].includes(e.key)){e.preventDefault();if(!e.repeat)beginManual(e);}});
$('hold').addEventListener('keyup',e=>{if([' ','Enter'].includes(e.key)){e.preventDefault();endManual();}});
$('hold').addEventListener('contextmenu',e=>e.preventDefault());
$('beads10').onclick=()=>run('beads10',async signal=>{clearBoard();startHeld();await sleep(10000,signal);stopHold();setStage('十秒，留一点余韵。',`模拟拼入 ${beadCount} 颗；声音已经停止，没有积压的落珠音。`,'连续拼入完成',100);});
$('quiz').onclick=()=>run('quiz',async signal=>{clearBoard();play('training.start');await sleep(380,signal);
  const outcomes=[true,true,false,true,false,false,true,true,true,true];
  for(let i=0;i<outcomes.length;i++){
    const ok=outcomes[i];setStage(`第 ${i+1} 题 · ${ok?'答对了':'再留意一下'}`,ok?'辨音判断正确，给一个轻轻的肯定。':'辨音判断有错；连续答错保持同样温和。','预设正误模拟',(i+1)*10);
    play(ok?'answer.correct':'answer.retry');cells.slice(0,(i+1)*14).forEach(c=>c.classList.add('on'));await sleep(850,signal);
  }
  setStage('这一组，练完了。','模拟奖励合并到账，只播放一段短声音。','答题模拟完成',100);play('reward.arrive');
});
$('ceremony').onclick=()=>run('ceremony',async signal=>{clearBoard();for(let i=0;i<4;i++){place(1);await sleep(130,signal);}
  cells.forEach(c=>c.classList.add('on'));sound.stopBus('bead');setStage('正在熨烫，慢慢融合。','轻柔的纹理跟随现有 1.8 秒仪式。','完成仪式 · 模拟',45);$('bead-board').classList.add('fusing');
  play('artwork.fuse');await sleep(1800,signal);$('bead-board').classList.remove('fusing');$('bead-board').classList.add('finished');
  const series=$('series').checked;setStage(series?'猫猫系列，集齐啦。':'一件小作品，完成了。',series?'系列音替代单件完成音，只庆祝一次。':'成品出现时绽放，随后恢复安静。','完成仪式 · 模拟',100);play(series?'series.complete':'artwork.complete');
});
function waitMedia(signal){return new Promise((resolve,reject)=>{
  const cleanup=()=>{voice.removeEventListener('ended',end);voice.removeEventListener('error',error);signal.removeEventListener('abort',abort);clearTimeout(timer);};
  const end=()=>{cleanup();resolve();};const error=()=>{cleanup();reject(Error('示范音加载失败'));};
  const abort=()=>{cleanup();reject(new DOMException('Stopped','AbortError'));};
  const timer=setTimeout(error,15000);voice.addEventListener('ended',end,{once:true});voice.addEventListener('error',error,{once:true});signal.addEventListener('abort',abort,{once:true});
});}
$('teaching').onclick=()=>run('teaching',async signal=>{
  play('training.start');await sleep(400,signal);$('teaching-state').textContent='示范正在读「安心」· 此时试插入奖励音，会保持安静';
  setStage('安心 · ān xīn','正在播放现有词库示范，所有装饰音让路。','教学衔接 · 模拟',15);
  // Bind before play; the paired rejection handler also covers media.play failures.
  const ended=waitMedia(signal);ended.catch(()=>{});
  try{await voice.play();await ended;}catch(e){if(!signal.aborted)controller?.abort();throw e;}
  await sleep(140,signal);if($('follow-cue').checked)play('follow.ready',{optional:true});
  $('teaching-state').textContent='轮到你跟读 · 2 秒计时，不判断发音';setStage('轮到你跟读。','这里仅模拟计时；不会因为时间到了，就说你读对了。','跟读计时',50);
  await sleep(2000,signal);$('teaching-state').textContent='跟读计时结束 · 安静收尾，没有发音正误判断';
  setStage('计时结束。','保持安静，准备进入下一条示范。','教学衔接完成',100);
});
$('intrude').onclick=async()=>{const own=intent;if(await sound.unlock()&&own===intent){const h=play('reward.arrive');
  $('teaching-state').textContent=h.started?'当前没有示范在播放，奖励音可以响起。':'已丢弃这次奖励音 · '+(h.reason==='teaching'?'教学示范优先，之后也不会补播。':h.reason==='muted'?'音效已关闭。':'播放器正在保持安静。');}};
document.addEventListener('visibilitychange',()=>{if(document.hidden){cancel();setStage('试听已暂停。','回来后手动点一次继续，不会补播先前的声音。');}});
window.addEventListener('blur',endManual);
window.addEventListener('pagehide',cancel);
window.addEventListener('keydown',e=>{if(e.key==='Escape'){$('stop').click();}});
// Read-only diagnostics and explicit manager handle for isolated acceptance checks.
window.soundLab={sound,getState:()=>({style,celebration,intent,holding,beadCount,flow:Boolean(controller),voiceTime:voice.currentTime,...sound.snapshot()}),cancel,
  dispose:async()=>{cancel();unbindVoice();await sound.dispose();}};
