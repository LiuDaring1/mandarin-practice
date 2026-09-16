/* Optional sound adapter: failure never blocks training. No training persistence or business rules. */
(() => {
  'use strict';
  const version='a-app-v4-2026-09-12';
  let manager=null;
  const teaching=new Map(),mediaLocks=new WeakMap(),seen=new Set();
  const noop=()=>{};
  const api=window.appSfx={
    unlock:()=>manager?.unlock().catch(noop),
    play:(id,options={})=>manager?.play(id,options),
    stop:()=>{manager?.stopAll();},
    stopBus:bus=>manager?.stopBus(bus),
    beginTeaching:()=>{
      const token=Symbol('teaching');teaching.set(token,manager?.beginTeaching()||null);
      return ()=>{teaching.get(token)?.();teaching.delete(token);};
    },
    settlement:(result,key)=>{
      if(!result||!(result.beads>0)||seen.has(key))return;
      seen.add(key);if(seen.size>128)seen.delete(seen.values().next().value);
      api.play(result.trioBonus>0?'day.complete':'reward.arrive',{eventKey:key});
    },
    snapshot:()=>manager?.snapshot()||{state:'loading',active:0,loaded:0,history:[]},
  };
  // Capturing covers both persistent teaching audio and dynamically rebuilt calibration videos.
  document.addEventListener('play',event=>{
    if(event.target instanceof HTMLMediaElement&&!mediaLocks.has(event.target))mediaLocks.set(event.target,api.beginTeaching());
  },true);
  for(const name of ['ended','pause','error','abort','emptied']) document.addEventListener(name,event=>{
    const release=mediaLocks.get(event.target);if(release){release();mediaLocks.delete(event.target);}
  },true);
  // Unlock on gestures only; no generic click sound, and no delayed replay of a missed event.
  for(const name of ['pointerdown','keydown','click']) document.addEventListener(name,event=>{
    if(name==='keydown'&&!['Enter',' '].includes(event.key))return;
    if(event.target.closest?.('button,input,summary'))api.unlock();
  },true);
  document.addEventListener('click',event=>{
    // Explicit configuration controls only; answer buttons and navigation stay out of this list.
    const target=event.target.closest?.('.duration-btn,.filter-chip,#filter-done,#filter-all,#sentence-filter-options button');
    if(target&&!target.disabled)api.play('ui.confirm');
  },true);
  api.ready=Promise.all([
    import(`/assets/sounds/sound-manager.js?v=${version}`),
    fetch(`/assets/sounds/manifest.json?v=${version}`,{cache:'no-cache'}).then(r=>{if(!r.ok)throw Error('manifest');return r.json();}),
  ]).then(([{SoundManager},manifest])=>{
    manager=new SoundManager(manifest,{baseURL:new URL('/assets/sounds/',location.href),storageKey:'pth-sound-preferences-v1'});
    // Until a dedicated settings page exists, always start enabled at 70%.
    // Keep saved preferences untouched for future settings; old mute/zero must not silently disable sound.
    manager.preferences = {...manager.preferences, muted:false, volume:.7};
    for(const token of teaching.keys())teaching.set(token,manager.beginTeaching());
    return manager.downloads;
  }).catch(noop); // Audio is optional; no visible settings or training failure on load errors.
})();
