/* Reusable, dependency-free sample manager. Only this class writes its own preference key.
 * No training data, timers that enqueue sounds, audio elements, or API mutations.
 */
export class SoundManager {
  constructor(manifest, {baseURL = new URL('./', import.meta.url), storageKey = 'pth-sound-lab-preferences-v1'} = {}) {
    this.manifest = manifest; this.baseURL = baseURL; this.storageKey = storageKey;
    this.preferences = {volume:.7, muted:false};
    try { const p=JSON.parse(localStorage.getItem(storageKey) || '{}');
      if (Number.isFinite(p.volume)) this.preferences.volume=Math.min(1,Math.max(0,p.volume));
      if (typeof p.muted==='boolean') this.preferences.muted=p.muted;
    } catch { /* private browsing/storage disabled: memory-only */ }
    this.buffers=new Map(); this.active=new Set(); this.last=new Map(); this.counters=new Map();
    this.seen=new Set(); this.teaching=new Set(); this.quietUntil=0; this.disposed=false;
    this.history=[]; this.maxObserved=0; this.onChange=()=>{};
    this.visibility=()=>{ if(document.hidden) { this.stopAll(true); this.ctx?.suspend().catch(()=>{}); } };
    this.pageHide=()=>{ this.stopAll(true); this.ctx?.suspend().catch(()=>{}); };
    document.addEventListener('visibilitychange',this.visibility);
    window.addEventListener('pagehide',this.pageHide);
    this.bytes=new Map(); this.downloads=this.preload();
  }
  async preload() {
    await Promise.all(this.manifest.sounds.flatMap(s=>s.variants).map(async file=>{
      try { const response=await fetch(new URL(file,this.baseURL)); if(!response.ok) throw Error(response.status);
        this.bytes.set(file,await response.arrayBuffer());
      } catch { this.record('asset-failed',file); }
    }));
  }
  async unlock() {
    if(this.disposed || document.hidden) return false;
    try {
      if(!this.ctx) {
        const Ctx=window.AudioContext||window.webkitAudioContext;
        this.ctx=new Ctx(); this.master=this.ctx.createGain();
        this.master.gain.value=this.preferences.muted?0:this.preferences.volume;
        this.master.connect(this.ctx.destination);
        this.ctx.onstatechange=()=>{ if(this.ctx.state!=='running') this.stopAll(true); this.onChange(); };
      }
      // Called directly from a pointer/key/click gesture, never on an automatic resume.
      await this.ctx.resume();
      if(!this.decoding) this.decoding=(async()=>{
        await this.downloads;
        await Promise.all([...this.bytes].map(async([file,bytes])=>{
          try { this.buffers.set(file,await this.ctx.decodeAudioData(bytes.slice(0))); }
          catch { this.record('decode-failed',file); }
        })); this.bytes.clear();
      })();
      await this.decoding; this.onChange();
      return !this.disposed && !document.hidden && this.ctx.state==='running';
    } catch { this.record('unavailable','AudioContext'); return false; }
  }
  record(action,id,extra={}) {
    this.history.push({time:Math.round(performance.now()),action,id,...extra});
    if(this.history.length>1500) this.history.shift();
  }
  setPreferences(change) {
    if(Number.isFinite(change.volume)) this.preferences.volume=Math.min(1,Math.max(0,change.volume));
    if(typeof change.muted==='boolean') this.preferences.muted=change.muted;
    if(this.preferences.muted || this.preferences.volume===0) this.stopAll();
    if(this.master) { const t=this.ctx.currentTime; const g=this.master.gain;
      g.cancelScheduledValues(t);g.setValueAtTime(g.value,t);
      g.linearRampToValueAtTime(this.preferences.muted?0:this.preferences.volume,t+.012); }
    try { localStorage.setItem(this.storageKey,JSON.stringify(this.preferences)); } catch { /* memory-only */ }
    this.onChange();
  }
  play(id,{style='a',eventKey=null,optional=false,variant=null}={}) {
    const skip=reason=>{ this.record('dropped',id,{reason});return {started:false,reason,done:Promise.resolve()}; };
    if(this.disposed || document.hidden || !this.ctx || this.ctx.state!=='running') return skip('inactive');
    if(this.preferences.muted || this.preferences.volume===0) return skip('muted');
    if(this.teaching.size || performance.now()<this.quietUntil) return skip('teaching');
    const s=this.manifest.sounds.find(s=>s.id===id&&s.style===style);
    if(!s) return skip('unknown');
    if(!s.default_enabled&&!optional) return skip('optional-off');
    if(eventKey&&this.seen.has(eventKey)) return skip('duplicate');
    const key=style+':'+id; const now=performance.now();
    if(now-(this.last.get(key)??-Infinity)<s.cooldown_ms) return skip('rate-limit');
    if([...this.active].some(v=>!v.stopping&&v.priority>s.priority)) return skip('priority');
    if(this.active.size>=4) return skip('voice-cap');
    if(s.bus==='bead'&&[...this.active].filter(v=>v.bus==='bead').length>=2) return skip('bead-cap');
    const index=variant===null?(this.counters.get(key)||0)%s.variants.length:Math.abs(variant)%s.variants.length;
    const file=s.variants[index],buffer=this.buffers.get(file);
    if(!buffer) return skip('not-loaded'); // No queue; missing feedback is never replayed later.
    for(const v of this.active) {
      if(v.priority<s.priority || (s.bus!=='bead'&&v.bus===s.bus)) this.stopVoice(v);
    }
    this.last.set(key,now);this.counters.set(key,index+1);
    if(eventKey) {this.seen.add(eventKey);if(this.seen.size>128)this.seen.delete(this.seen.values().next().value);}
    const source=this.ctx.createBufferSource(),gain=this.ctx.createGain();
    source.buffer=buffer; gain.gain.value=s.gain; source.connect(gain);gain.connect(this.master);
    let resolve;const done=new Promise(r=>{resolve=r;});
    const voice={source,gain,bus:s.bus,priority:s.priority,stopping:false,id};
    voice.finish=()=>{if(voice.finished)return;voice.finished=true;this.active.delete(voice);source.disconnect();gain.disconnect();resolve();this.onChange();};
    source.onended=voice.finish;
    this.active.add(voice);this.maxObserved=Math.max(this.maxObserved,this.active.size);
    source.start(); this.record('played',id,{style,variant:index,voices:this.active.size});this.onChange();
    return {started:true,done,duration:buffer.duration,stop:()=>this.stopVoice(voice)};
  }
  stopVoice(v,immediate=false) {
    if(immediate){try{v.source.stop();}catch{}v.finish();return;}
    if(v.stopping)return;v.stopping=true;
    const t=this.ctx.currentTime;
    try {v.gain.gain.cancelScheduledValues(t);v.gain.gain.setValueAtTime(v.gain.gain.value,t);
      v.gain.gain.linearRampToValueAtTime(0,t+.008);v.source.stop(t+.010);}catch{/* already ended */}
  }
  stopBus(bus){for(const v of this.active)if(v.bus===bus)this.stopVoice(v);}
  stopAll(immediate=false){for(const v of this.active)this.stopVoice(v,immediate);}
  beginTeaching() {
    const token=Symbol('teaching');this.teaching.add(token);this.stopAll();this.onChange();
    return ()=>{this.teaching.delete(token);this.quietUntil=performance.now()+120;this.onChange();};
  }
  bindMedia(media) {
    let release=null;
    const begin=()=>{if(!release)release=this.beginTeaching();};
    const end=()=>{release?.();release=null;};
    const events=['ended','pause','error','abort','emptied'];
    media.addEventListener('play',begin);events.forEach(e=>media.addEventListener(e,end));
    if(!media.paused)begin();
    return ()=>{end();media.removeEventListener('play',begin);events.forEach(e=>media.removeEventListener(e,end));};
  }
  snapshot(){return {state:this.ctx?.state||'locked',loaded:this.buffers.size,active:this.active.size,
    maxObserved:this.maxObserved,teaching:this.teaching.size,preferences:{...this.preferences},history:this.history.slice()};}
  async dispose(){if(this.disposed)return;this.disposed=true;this.stopAll(true);
    document.removeEventListener('visibilitychange',this.visibility);window.removeEventListener('pagehide',this.pageHide);
    if(this.ctx){this.ctx.onstatechange=null;await this.ctx.close().catch(()=>{});}this.buffers.clear();this.bytes.clear();this.teaching.clear();}
}
