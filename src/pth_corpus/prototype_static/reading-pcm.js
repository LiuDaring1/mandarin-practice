"use strict";
// Deterministic mono PCM conversion, including an anti-alias filter for 44.1/48k microphones.
(() => {
  function resample(samples, rate) {
    if (rate === 16000) return samples.slice(0, 944000);
    const count = Math.min(944000, Math.floor(samples.length * 16000 / rate));
    const output = new Float32Array(count), radius = 20, phases = 256;
    const cutoff = .45 * Math.min(1, 16000 / rate), tables = [];
    for (let phase = 0; phase < phases; phase++) {
      const weights = new Float64Array(radius * 2);
      for (let tap = -radius + 1; tap <= radius; tap++) {
        const distance = tap - phase / phases;
        const x = 2 * cutoff * distance;
        const sinc = Math.abs(x) < 1e-9 ? 1 : Math.sin(Math.PI * x) / (Math.PI * x);
        weights[tap + radius - 1] = 2 * cutoff * sinc * (.5 + .5 * Math.cos(Math.PI * distance / radius));
      }
      tables.push(weights);
    }
    for (let n = 0; n < count; n++) {
      const position = n * rate / 16000, center = Math.floor(position);
      const weights = tables[Math.min(phases - 1, Math.floor((position-center)*phases))];
      let value = 0, sum = 0;
      for (let k = 0; k < weights.length; k++) {
        const index = center + k - radius + 1;
        if (index >= 0 && index < samples.length) { value += samples[index] * weights[k]; sum += weights[k]; }
      }
      output[n] = sum ? value / sum : 0;
    }
    return output;
  }
  function wav(samples, rate) {
    const rendered = resample(samples, rate);
    const out = new ArrayBuffer(44 + rendered.length * 2), view = new DataView(out);
    const text = (at, value) => [...value].forEach((c,i) => view.setUint8(at+i,c.charCodeAt(0)));
    text(0,'RIFF');view.setUint32(4,out.byteLength-8,true);text(8,'WAVE');text(12,'fmt ');
    view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);
    view.setUint32(24,16000,true);view.setUint32(28,32000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);
    text(36,'data');view.setUint32(40,rendered.length*2,true);
    rendered.forEach((v,i)=>view.setInt16(44+i*2,Math.max(-32768,Math.min(32767,Math.round(v*32768))),true));
    return out;
  }
  window.readingPcm = {resample,wav};
})();
