"use strict";
// Record only the learner's turn. WAV encoding is explicit; no WebM is sent as WAV.
window.readingAssessment = (() => {
  let stream, context, node, source, sink, enabled = false, chunks = [], frames = 0;
  let required = false, providerAvailable = false, lastError = null;
  let serial = 0, active = false, flush, controller, dismiss, captureTimer, locallyVoiced = false;
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
    controller?.abort(); controller = null;
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
    try {
      const response = await fetch('/api/assessment/status');
      const status = await response.json();
      required = Boolean(status.recording_required ?? status.configured); providerAvailable = Boolean(status.available);
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
  async function wav() {
    await new Promise(resolve => { flush = resolve; node.port.postMessage('stop'); });
    active = false; clearTimeout(captureTimer);
    const samples = new Float32Array(frames);
    let offset = 0; chunks.forEach(c => { samples.set(c, offset); offset += c.length; });
    locallyVoiced = samples.length > 4000 && Math.sqrt(samples.reduce((sum,v)=>sum+v*v,0)/samples.length) >= 0.004;
    if (!frames) return null;
    const out = window.readingPcm.wav(samples, context.sampleRate);
    chunks=[];frames=0;return out;
  }
  async function grade(kind, id, retry) {
    if (!enabled) return {advance:true,complete:!required};
    const token = serial, el = panel(kind);
    el.textContent = '正在评测…';
    let result;
    try {
      const audio = await wav();
      if (token !== serial) return {advance:false,complete:false};
      if (!audio) result = {status:'no_speech',message:'没有检测到朗读，请再读一次'};
      else if (!providerAvailable) result = {status:locallyVoiced?'unavailable':'no_speech',message:locallyVoiced?'已检测到发声，评测暂不可用':'没有检测到朗读，请再读一次'};
      else {
        controller = new AbortController();
        const timeout = setTimeout(()=>controller?.abort(),25000);
        try {
          const response = await fetch(`/api/assessment/${kind}/${encodeURIComponent(id)}?attempt_id=${crypto.randomUUID()}`, {
            method:'POST',headers:{'Content-Type':'audio/wav'},body:audio,signal:controller.signal
          });
          if (!response.ok) throw new Error('assessment');
          result = await response.json();
        } finally {clearTimeout(timeout);}
      }
    } catch {result={status:'unavailable',message:'这次未能评测，可重读或继续'};}
    if(token !== serial) return {advance:false,complete:false};
    el.replaceChildren();
    const summary=document.createElement('div');
    const score=result.score ?? result.accuracy;
    summary.textContent=result.status==='ok' ? (score == null ? '已完成评测' : `朗读评分 ${Math.round(score)} 分`) : result.message || '这次未能评测';
    el.append(summary);
    const weak=(result.words||[]).filter(w=>[2,3,4].includes(w.tag)||(w.accuracy != null && w.accuracy<70)).map(w=>w.text).filter(Boolean);
    if(weak.length){const advice=document.createElement('div');advice.textContent=`建议再练：${[...new Set(weak)].join('、')}`;el.append(advice);}
    return new Promise(resolve=>{
      let timer;
      const settle=value=>{clearTimeout(timer);dismiss=null;resolve(value);};
      dismiss=settle;
      const again=document.createElement('button');again.className='ghost-btn';again.textContent='再读一次';
      again.onclick=()=>{settle({advance:false,complete:false});retry();};
      const next=document.createElement('button');next.className='ghost-btn';next.textContent=result.status==='no_speech'?'跳过这条':'继续';
      const complete=result.status==='ok' || (locallyVoiced && result.status!=='no_speech');
      next.onclick=()=>settle({advance:true,complete});el.append(again,next);
      // Silence requires an explicit retry/skip. Errors are never converted to a zero score.
      if(result.status!=='no_speech')timer=setTimeout(()=>settle({advance:true,complete}),2200);
    });
  }
  return {prepare,start,grade,cancel,close,get enabled(){return enabled;},get required(){return required;},get lastError(){return lastError;}};
})();
