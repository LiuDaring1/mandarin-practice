"use strict";
// Record only the learner's turn. WAV encoding is explicit; no WebM is sent as WAV.
window.readingAssessment = (() => {
  let stream, context, node, source, sink, enabled = false, chunks = [], frames = 0;
  let required = false, lastError = null;
  let serial = 0, active = false, flush, dismiss, captureTimer, locallyVoiced = false;
  let run = null;
  const panels = {};
  function panel(kind) {
    if (!panels[kind]) {
      const el = document.createElement('div');
      el.className = 'assessment-panel'; el.id = `assessment-${kind}`;
      el.setAttribute('aria-live', 'polite');
      document.getElementById(kind === 'sentence' ? 'sentence-status' : 'status').after(el);
      panels[kind] = el;
    }
    return panels[kind];
  }
  function cancel() {
    serial++; active = false; chunks = []; frames = 0;
    clearTimeout(captureTimer); node?.port.postMessage('stop');
    if (flush) { flush(); flush = null; }
    if (dismiss) { dismiss({advance:false,complete:false}); dismiss = null; }
    Object.values(panels).forEach(el => { el.replaceChildren(); });
  }
  async function close() {
    cancel(); enabled = false;
    stream?.getTracks().forEach(t => t.stop()); stream = null;
    source?.disconnect(); node?.disconnect(); sink?.disconnect();
    const old = context; context = null; node = null; source = null; sink = null;
    if (old && old.state !== 'closed') await old.close().catch(() => {});
  }
  async function prepare() {
    // Create/resume within the start-button gesture, before any network await.
    // Safari and embedded browsers otherwise keep a later-created context suspended.
    let candidate;
    try { candidate = new AudioContext(); candidate.resume().catch(()=>{}); } catch { /* unsupported browser */ }
    await close(); required = false; lastError = null;
    run = {id: crypto.randomUUID(), uploads: new Set(), errors: 0};
    try {
      const response = await fetch('/api/assessment/status');
      const status = await response.json();
      required = Boolean(status.recording_required ?? status.configured);
      if (!required || !navigator.mediaDevices?.getUserMedia || !candidate) {
        candidate?.close().catch(()=>{});return false;
      }
      context = candidate;
      stream = await navigator.mediaDevices.getUserMedia({audio:{channelCount:1, echoCancellation:true, noiseSuppression:true},video:false});
      let ready = false;
      if (context.audioWorklet && window.AudioWorkletNode) {
        try {
          ready = await Promise.race([
            context.audioWorklet.addModule('/assets/recorder-worklet.js').then(()=>true),
            new Promise(resolve=>setTimeout(()=>resolve(false),1800))
          ]);
        } catch { /* Embedded browsers may not load worklet modules. */ }
      }
      source = context.createMediaStreamSource(stream);
      if (ready) node = new AudioWorkletNode(context, 'reading-recorder');
      else {
        node = context.createScriptProcessor(2048,1,1);
        let recording = false;
        const port = {onmessage:null,postMessage(command){
          recording = command === 'start';
          if (command === 'stop') queueMicrotask(()=>port.onmessage?.({data:{done:true}}));
        }};
        node.port = port;
        node.onaudioprocess = event => {
          if (recording) port.onmessage?.({data:{samples:event.inputBuffer.getChannelData(0).slice()}});
        };
      }
      sink = context.createGain(); sink.gain.value = 0;
      source.connect(node); node.connect(sink); sink.connect(context.destination);
      node.port.onmessage = ({data}) => {
        if (data.done && flush) { flush(); flush = null; }
        if (data.samples && active && frames < context.sampleRate * 59) {
          chunks.push(data.samples); frames += data.samples.length;
        }
      };
      if (context.state !== 'running') {
        await Promise.race([context.resume(), new Promise(resolve=>setTimeout(resolve,5000))]);
        if (context.state !== 'running') throw new Error('Audio context did not start');
      }
      enabled = true; return true;
    } catch (error) {
      lastError = `${error.name}: ${error.message}`;
      await close();
      if (candidate?.state !== 'closed') candidate?.close().catch(()=>{});
      return false;
    }
  }
  function start(kind) {
    cancel();
    if (!enabled || !node) {
      if (required) panel(kind).textContent = "麦克风未开启，本次仅听示范，不计朗读完成";
      return;
    }
    panel(kind).textContent = '正在听你朗读…';
    active = true; node.port.postMessage('start');
    captureTimer = setTimeout(() => node?.port.postMessage('stop'), 59000);
  }
  async function wav(token) {
    await new Promise(resolve => { flush = resolve; node.port.postMessage('stop'); });
    if (token !== serial) return null;
    active = false; clearTimeout(captureTimer);
    const samples = new Float32Array(frames);
    let offset = 0; chunks.forEach(c => { samples.set(c, offset); offset += c.length; });
    // Require sustained energy, so a click alone is not a completed turn.
    let voicedSamples = 0, first = samples.length, last = 0;
    const block = Math.round(context.sampleRate * .02);
    for (let i = 0; i < samples.length; i += block) {
      const end = Math.min(samples.length, i + block);
      let energy = 0;
      for (let j = i; j < end; j++) energy += samples[j] * samples[j];
      if (Math.sqrt(energy / (end - i)) >= .004) { voicedSamples += end - i;first=Math.min(first,i);last=end; }
    }
    locallyVoiced = voicedSamples / context.sampleRate >= .25;
    if (!frames) return null;
    const padding = Math.round(context.sampleRate * .2);
    const trimmed = locallyVoiced ? samples.slice(Math.max(0,first-padding),Math.min(samples.length,last+padding)) : samples;
    const out = window.readingPcm.wav(trimmed, context.sampleRate);
    chunks=[];frames=0;return out;
  }
  function upload(current, kind, id, audio, passNo) {
    const work = (async () => {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 15000);
      try {
        const query = new URLSearchParams({attempt_id:crypto.randomUUID(),session_id:current.id,pass_no:String(passNo)});
        const response = await fetch(`/api/reading/attempts/${kind}/${encodeURIComponent(id)}?${query}`, {
          method:'POST',headers:{'Content-Type':'audio/wav'},body:audio,signal:controller.signal
        });
        if (!response.ok || !['pending','ok'].includes((await response.json()).status)) current.errors++;
      } catch { current.errors++; }
      finally { clearTimeout(timeout); }
    })();
    current.uploads.add(work); work.finally(() => current.uploads.delete(work));
  }
  async function grade(kind, id, retry, passNo = 1) {
    if (!enabled) return {advance:true,complete:!required};
    const token = serial, current = run, el = panel(kind);
    const audio = await wav(token);
    if(token !== serial) return {advance:false,complete:false};
    el.replaceChildren();
    if (audio && locallyVoiced) {
      upload(current, kind, id, audio, passNo);
      return {advance:true,complete:true};
    }
    const summary=document.createElement('div');
    summary.textContent='没有检测到持续朗读，请重读或跳过';
    el.append(summary);
    return new Promise(resolve=>{
      const settle=value=>{dismiss=null;resolve(value);};
      dismiss=settle;
      const again=document.createElement('button');again.className='ghost-btn';again.textContent='再读一次';
      again.onclick=()=>{settle({advance:false,complete:false});retry();};
      const next=document.createElement('button');next.className='ghost-btn';next.textContent='跳过这遍';
      next.onclick=()=>settle({advance:true,complete:false});el.append(again,next);
    });
  }
  function renderWeak(root, weak) {
    for (const item of weak) {
      const card = document.createElement('div'); card.className='reading-weak';
      const title=document.createElement('strong');
      title.textContent=`${item.text} · ${item.pinyin} · ${item.final}${item.sessions>1?' · 多轮出现':''}`;
      const context=document.createElement('p');context.textContent=item.context;
      card.append(title,context);root.append(card);
    }
  }
  function mountSummary(parent, startReview) {
    const current = run;
    if (!current || !required) return;
    const box=document.createElement('section');box.className='reading-summary';
    box.innerHTML='<h2>本次朗读回顾</h2><p role="status">正在整理后台结果…</p><div class="reading-details"></div>';
    parent.querySelector('.complete-actions').before(box);
    const status=box.querySelector('[role=status]'), details=box.querySelector('.reading-details');
    let timer;
    const update=async()=>{
      if (!box.isConnected || run !== current) return;
      try {
        const response=await fetch(`/api/reading/session/${current.id}`);
        if(!response.ok)throw new Error('summary');
        const result=await response.json();
        if(!box.isConnected || run !== current)return;
        const uploading=current.uploads.size;
        status.textContent=`已评测 ${result.assessed} 段${result.pending+uploading?` · ${result.pending+uploading} 段整理中`:''}`;
        details.replaceChildren();
        const note=document.createElement('p');
        note.textContent=!result.diagnostics_ready
          ? '鼻音诊断仍在验证，本次不生成自动错音结论或复练建议。'
          : result.target_observations
          ? `获得 ${result.target_observations} 次目标鼻韵母反馈。低分仅提示复练，可能包含声调影响，不判定 n/ng 混淆。`
          : '本次暂无可用的鼻韵母细节，不能据此判断已掌握或读错。';
        details.append(note);
        if(result.possible_incomplete){const p=document.createElement('p');p.textContent=`${result.possible_incomplete} 条内容可能未读完整，下次可以放慢重读；这不是鼻音错误结论。`;details.append(p);}
        if(result.limited){const p=document.createElement('p');p.textContent=`${result.limited} 段未获得可用音素细节，未纳入薄弱项。`;details.append(p);}
        if(result.unavailable+current.errors){const p=document.createElement('p');p.textContent=`${result.unavailable+current.errors} 段未能评测，不记零分，不影响本次练习奖励。`;details.append(p);}
        if(result.no_speech){const p=document.createElement('p');p.textContent=`${result.no_speech} 段未识别到有效朗读，可在下次重读。`;details.append(p);}
        renderWeak(details,result.weak);
        if(result.weak.length){const button=document.createElement('button');button.className='ghost-btn';button.textContent='练这些音';button.onclick=startReview;details.append(button);}
        if (result.pending || uploading) timer=setTimeout(update,1500);
      }catch{status.textContent='暂时未能加载回顾，可重试；练习已结束。';
        const button=document.createElement('button');button.className='ghost-btn';button.textContent='重试回顾';button.onclick=()=>{button.remove();update();};details.append(button);}
    };
    update();
    // Detached summaries never update a later session, and never cancel uploads.
    return ()=>clearTimeout(timer);
  }
  async function mountReview(parent, startReview, home) {
    parent.replaceChildren();
    const title=document.createElement('h1');title.textContent='朗读回顾';parent.append(title);
    const note=document.createElement('p');note.textContent='正在读取朗读记录…';parent.append(note);
    const back=document.createElement('button');back.className='ghost-btn';back.textContent='返回首页';back.onclick=home;parent.append(back);
    try {
      const response=await fetch('/api/reading/review');if(!response.ok)throw new Error('review');
      const result=await response.json();if(!note.isConnected)return;
      note.textContent=!result.diagnostics_ready?'鼻音诊断仍在验证，暂不生成自动复练建议。已提交的录音评测记录会保留，录音文件不会保存。':result.weak.length?'从原句里的薄弱音出发，再换句子练。建议项来自鼻韵母评分，可能包含声调影响。':'暂时没有鼻韵母复练建议；这不代表所有发音都已掌握。';
      const content=document.createElement('div');back.before(content);renderWeak(content,result.weak);
      if(result.weak.length){const button=document.createElement('button');button.className='primary-btn tone-green';button.textContent='开始专项复练';button.onclick=startReview;content.append(button);}
      const heading=document.createElement('h2');heading.textContent='最近的朗读评测';content.append(heading);
      for(const session of result.sessions){const p=document.createElement('p');
        const date=session.created?new Date(session.created*1000).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}):'';
        p.textContent=`${date} ${session.kind==='sentence'?'句子':'字词'} · ${session.submitted} 段录音 · 已评 ${session.assessed} 段${session.pending?` · ${session.pending} 段处理中`:''}${result.diagnostics_ready?` · 建议复练 ${session.weak.length} 项`:''}`;content.append(p);}
    }catch{note.textContent='暂时未能读取朗读记录，请稍后再试。';}
  }
  return {prepare,start,grade,cancel,close,mountSummary,mountReview,
    get enabled(){return enabled;},get required(){return required;},get lastError(){return lastError;}};
})();
