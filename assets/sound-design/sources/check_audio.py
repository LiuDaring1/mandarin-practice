#!/usr/bin/env python3
"""WAV decode/edge/peak checks, including 4x FFT true-peak estimate (not a listening test)."""
from pathlib import Path
import hashlib,json,wave
import numpy as np
root=Path(__file__).resolve().parents[1]
rows=[]
for p in sorted((root/'exports').glob('*.wav')):
    with wave.open(str(p),'rb') as w:
        assert w.getnchannels()==1 and w.getsampwidth()==2 and w.getframerate()==44100
        x=np.frombuffer(w.readframes(w.getnframes()),'<i2').astype(float)/32768
    up=np.fft.irfft(np.fft.rfft(x),n=len(x)*4)*4
    db=lambda v:round(float(20*np.log10(max(v,1e-12))),2)
    row={'file':p.name,'duration_ms':round(len(x)/44100*1000,2),'sample_peak_dbfs':db(np.max(np.abs(x))),
      'rms_dbfs':db(np.sqrt(np.mean(x*x))),'estimated_true_peak_dbfs':db(np.max(np.abs(up))),
      'first_sample':float(x[0]),'last_sample':float(x[-1]),'clipped_samples':int((np.abs(x)>=32767/32768).sum()),
      'max_sample_step':round(float(np.max(np.abs(np.diff(x)))),6),'first_1ms_peak':round(float(np.max(np.abs(x[:44]))),6),
      'last_1ms_peak':round(float(np.max(np.abs(x[-44:]))),6),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    assert row['first_sample']==row['last_sample']==0 and row['clipped_samples']==0
    assert row['estimated_true_peak_dbfs'] < -15
    rows.append(row)
report={'status':'passed','sample_rate':44100,'files':rows,'listening_status':'机器检查通过；耳机与手机外放人耳听检未完成'}
(root/'qa/audio-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(f'{len(rows)} WAV passed; highest estimated true peak: {max(r["estimated_true_peak_dbfs"] for r in rows)} dBFS')
