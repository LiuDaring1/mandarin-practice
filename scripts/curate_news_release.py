"""Curate a paired news release, retaining strict checks and holding suspect sentences.

News is a selection from a larger corpus: failed conversion candidates are never
waived or silently repaired by changing the speech-loss thresholds. Original
failed reports and attempted local repairs remain available for later review.
"""
from pathlib import Path
import json
import wave

import numpy as np
import voice_conversion_batch as vc
import voice_conversion_integrity as integrity


def local_match(source, converted, rate=16000):
    """Require this sentence's energy pattern to match near the page's measured lag."""
    hop=rate//100
    def envelope(x):
        x=x[:len(x)//hop*hop].reshape(-1,hop)
        return np.sqrt((x*x).mean(axis=1))
    a,b=envelope(source),envelope(converted)
    radius=12
    n=min(len(a),len(b))-2*radius
    if n<100:return 0.0
    x=a[radius:radius+n];x=x-x.mean()
    y=b[:n+2*radius]
    scores=[]
    for i in range(2*radius+1):
        z=y[i:i+n];z=z-z.mean()
        scores.append(float(np.dot(x,z)/(np.linalg.norm(x)*np.linalg.norm(z)+1e-12)))
    return max(scores)


def held_windows(clip,timing):
    median=timing.get('median_lag_ms',0)
    bad=[w for w in timing.get('windows',[]) if w['correlation']<.65 or abs(w['lag_ms']-median)>60]
    return [w['source_start'] for w in bad if clip['start']<w['source_start']+8 and clip['end']>w['source_start']]


def curate(data, minimum=450):
    data=data.resolve();out=data/'derived/news-sentence-v1';voices=data/'derived/voice-conversion'
    selection=json.loads((out/'selection.json').read_text());expected={r['sentence_id']:r for r in selection}
    results={};bindings={};held={}
    for voice,name in [('news-female','news-sentences-female-v1'),('news-male','news-sentences-male-v1')]:
        batch=voices/name;jobs=[j for j in json.loads((batch/'queue.json').read_text())['jobs'] if j['kind']!='repair']
        if {c['id'] for j in jobs for c in j['clips']}!=set(expected):raise ValueError('Incomplete source queue')
        good={};bad={};evidence=[]
        for job in jobs:
            source_path=Path(job['source']);export=batch/'exports'/job['export_name']
            report_path=batch/'reports'/(job['id']+'__conversion-integrity.json')
            report=json.loads(report_path.read_text())
            if vc.digest(source_path)!=job['source_sha256'] or vc.digest(export)!=report['export_sha256']:raise ValueError('Source or export changed')
            if report['job']!=job['id'] or not report['file_integrity'] or report['untreated_input_suspected']:raise ValueError('Invalid or untreated export')
            timing=report['timing'];windows=timing.get('windows',[])
            # Three page windows establish the common lag (as in local-repair
            # assembly); every selected sentence must independently pass .65.
            # Bad page windows are still held, including all overlapping clips.
            if len(windows)!=11 or sum(w['correlation']>=.65 for w in windows)<3:raise ValueError('Insufficient page identity evidence')
            offset=timing['median_lag_ms']/1000
            if abs(offset)>.3:raise ValueError('Unexpected news conversion delay')
            x=vc.decode_audio(source_path);y=vc.decode_audio(export)
            checks={r['id']:r for r in report['clips']}
            if set(checks)!={c['id'] for c in job['clips']}:raise ValueError('Incomplete per-sentence audit')
            evidence.append({'job':job['id'],'source':str(source_path),'source_sha256':job['source_sha256'],
                'export':str(export),'export_sha256':report['export_sha256'],'report':str(report_path),'report_sha256':vc.digest(report_path)})
            for index,c in enumerate(job['clips']):
                sid=c['id'];row=expected[sid];reasons=[]
                original=vc.safe_path(data,row['original_relative_path'])
                if c['relative_path']!=row['original_relative_path'] or vc.digest(original)!=row['clip_sha256']:raise ValueError('Sentence identity changed')
                if checks[sid]['new_loss'] or checks[sid]['source_silent']:reasons.append('new energy loss or silent source')
                if held_windows(c,timing):reasons.append('uncertain page timing window')
                before=x[round(c['start']*16000):round(c['end']*16000)]
                with wave.open(str(original),'rb') as stream:
                    original_pcm=np.frombuffer(stream.readframes(stream.getnframes()),dtype='<i2').astype(np.float32)/32768
                if not np.array_equal(before,original_pcm):raise ValueError('Packet does not contain the original sentence')
                after=y[round((c['start']+offset)*16000):round((c['end']+offset)*16000)]
                score=local_match(before,after)
                if score<.65:reasons.append('uncertain sentence energy match')
                if integrity.unchanged_waveform(before,after):reasons.append('untreated sentence suspected')
                if reasons:bad[sid]={'reasons':reasons,'correlation':round(score,4)};continue
                left=0 if index==0 else (job['clips'][index-1]['end']+c['start'])/2+offset
                right=len(y)/16000 if index+1==len(job['clips']) else (c['end']+job['clips'][index+1]['start'])/2+offset
                start=max(left,c['start']+offset-.06);end=min(right,c['end']+offset+.12)
                audio=y[max(0,round(start*16000)):round(end*16000)]
                if len(audio)<len(before)-320:bad[sid]={'reasons':['truncated output']};continue
                path=batch/'staged-news-v1'/(sid+'.wav');path.parent.mkdir(exist_ok=True)
                pcm=np.clip(np.rint(audio*32768),-32768,32767).astype('<i2').tobytes()
                if path.exists():
                    with wave.open(str(path),'rb') as stream:
                        if (stream.getnchannels(),stream.getsampwidth(),stream.getframerate())!=(1,2,16000):raise ValueError('Staged WAV format changed')
                        if stream.readframes(stream.getnframes())!=pcm:raise ValueError('Refuse to overwrite staged news')
                else:
                    with wave.open(str(path),'wb') as stream:stream.setparams((1,2,16000,0,'NONE','not compressed'));stream.writeframes(pcm)
                good[sid]={'job':job['id'],'kind':'sentence','voice':voice,'original_relative_path':c['relative_path'],
                    'replacement':str(path),'sha256':vc.digest(path),'audio':{'duration':len(audio)/16000,'sample_rate':16000,'channels':1},
                    'correlation':round(score,4)}
        results[voice]=good;bindings[voice]=evidence;held[voice]=bad
    paired=set(results['news-female'])&set(results['news-male'])
    report={'version':1,'requested':len(selection),'accepted':len(paired),'minimum':minimum,
        'held':held,'bindings':bindings,'selection_sha256':vc.digest(out/'selection.json'),
        'originals':[{'path':r['original_relative_path'],'sha256':r['clip_sha256']} for r in selection],
        'scope':'sentence curation: strict original energy-loss thresholds; uncertain candidates held, no waivers'}
    vc.write_json(out/'paired-curation-report.json',report)
    if len(paired)<minimum:raise ValueError(f'Only {len(paired)} paired sentences pass; need {minimum}')
    rows=[r for r in selection if r['sentence_id'] in paired]
    manifests={voice:{'version':1,'jobs':len(bindings[voice]),'clip_count':len(paired),
        'clips':{sid:results[voice][sid] for sid in sorted(paired)},'curation_report_sha256':vc.digest(out/'paired-curation-report.json')}
        for voice in results}
    return rows,manifests


def verify(data,manifest):
    out=data/'derived/news-sentence-v1';path=out/'paired-curation-report.json'
    if vc.digest(path)!=manifest['curation_report_sha256']:raise ValueError('Curation evidence changed')
    report=json.loads(path.read_text())
    if vc.digest(out/'selection.json')!=report['selection_sha256']:raise ValueError('Selected sources changed')
    for row in report['originals']:
        if vc.digest(vc.safe_path(data,row['path']))!=row['sha256']:raise ValueError('Original clip changed')
    for rows in report['bindings'].values():
        for row in rows:
            for key in ('source','export','report'):
                if vc.digest(Path(row[key]))!=row[key+'_sha256']:raise ValueError('Conversion evidence changed')
    for row in manifest['clips'].values():
        if vc.digest(vc.safe_path(data,row['replacement']))!=row['sha256']:raise ValueError('Staged voice changed')
