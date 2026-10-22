"""Exercise the browser encoder in JS, not an equivalent Python implementation."""
from pathlib import Path
import subprocess


def test_browser_pcm_headers_duration_clipping_and_antialias_filter():
    root=Path(__file__).resolve().parents[1]
    script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const sandbox={window:{}};vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('src/pth_corpus/prototype_static/reading-pcm.js','utf8'),sandbox);
const codec=sandbox.window.readingPcm;
for(const rate of [16000,44100,48000]){
  const samples=Float32Array.from({length:rate*2},(_,i)=>.5*Math.sin(2*Math.PI*1000*i/rate));
  const bytes=codec.wav(samples,rate),v=new DataView(bytes);
  assert.equal(bytes.byteLength,44+64000);assert.equal(v.getUint32(24,true),16000);
  assert.equal(v.getUint16(22,true),1);assert.equal(v.getUint16(34,true),16);
  const out=codec.resample(samples,rate);assert.equal(out.length,32000);
  const rms=Math.sqrt(out.slice(100,-100).reduce((s,x)=>s+x*x,0)/(out.length-200));
  assert(Math.abs(rms-Math.sqrt(.125))<.02);
}
const wave=frequency=>Float32Array.from({length:48000},(_,i)=>Math.sin(2*Math.PI*frequency*i/48000));
const rms=a=>Math.sqrt(a.slice(100,-100).reduce((sum,x)=>sum+x*x,0)/(a.length-200));
assert(rms(codec.resample(wave(12000),48000))<.03*rms(codec.resample(wave(1000),48000)));
const clipped=new DataView(codec.wav(new Float32Array([2,-2]),16000));
assert.equal(clipped.getInt16(44,true),32767);assert.equal(clipped.getInt16(46,true),-32768);
console.log('PCM duration, WAV headers, clipping and alias rejection passed');
'''
    result=subprocess.run(['node','-e',script],cwd=root,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
