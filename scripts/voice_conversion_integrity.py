"""Compare converted speech with its source without rejudging corpus labels/bounds."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import wave
import numpy as np
import voice_conversion_batch as vc


def unchanged_waveform(source, converted, rate=16000):
    """Catch an accidental export of untreated input, allowing gain and small delays."""
    from scipy.signal import correlate
    width, radius = rate, round(rate*.25)
    length = min(len(source),len(converted))
    scores=[]
    for start in np.linspace(radius, length-width-radius, 7,dtype=int):
        if start < radius:
            continue
        x=source[start:start+width].astype(float)
        if np.sqrt(np.mean(x*x)) < .003:
            continue
        x=x-x.mean()
        y=converted[start-radius:start+width+radius].astype(float)
        sums=np.r_[0,np.cumsum(y)]; squares=np.r_[0,np.cumsum(y*y)]
        variance=squares[width:]-squares[:-width]-(sums[width:]-sums[:-width])**2/width
        corr=correlate(y,x,mode='valid',method='fft')
        score=np.max(np.abs(corr)/(np.linalg.norm(x)*np.sqrt(np.maximum(variance,0))+1e-12))
        scores.append(float(score))
    return len(scores)>=3 and sum(s>.995 for s in scores)>=3


def lost_speech(source, converted, rate=16000):
    """Flag sustained newly absent energy; inherited silence is deliberately allowed."""
    n = min(len(source), len(converted))
    hop = round(rate * .02)
    n = n // hop * hop
    if not n:
        return []
    a = np.sqrt(np.mean(source[:n].reshape(-1,hop)**2,axis=1))
    b = np.sqrt(np.mean(converted[:n].reshape(-1,hop)**2,axis=1))
    ar, br = np.quantile(a,.95), np.quantile(b,.95)
    missing = (a > max(.001, ar*.06)) & (b < max(.0001,br*.006))
    # Close only short gaps so isolated 20 ms crossings do not hide a missing vowel.
    from scipy.ndimage import binary_closing
    missing = binary_closing(missing, structure=np.ones(3),border_value=0)
    changes = np.diff(np.r_[False,missing,False].astype(int))
    return [{'start':round(s*.02,3),'end':round(e*.02,3)}
            for s,e in zip(np.flatnonzero(changes==1),np.flatnonzero(changes==-1))
            if e-s>=10]


def review(batch, job_id, variant=None):
    args=argparse.Namespace(batch=batch,job=job_id)
    job=vc.job_for(args)
    original=Path(job['source'])
    if vc.digest(original)!=job['source_sha256']:
        raise ValueError('Source changed')
    source=vc.decode_audio(original)
    page_audio=vc.decode_audio(batch/'exports'/job['export_name'])
    passthrough=unchanged_waveform(source,page_audio)
    if variant:
        folder=vc.safe_path(batch,'staged-'+variant+'/'+job_id)
        manifest=json.loads((folder/'manifest.json').read_text())
        candidates={c['id']:c for c in manifest['clips']}
        timing=manifest['accepted_timing']
        identity=(manifest['job']==job_id and manifest['voice']==job['voice'] and
                  len(candidates)==len(job['clips']) and len(candidates)==len(manifest['clips']))
        rows=[]
        for clip in job['clips']:
            c=candidates[clip['id']]
            identity &= all(c[k]==clip[k] for k in ['relative_path','start','end'])
            path=vc.safe_path(folder,c['relative_path'])
            identity &= vc.digest(path)==c['sha256']
            # Candidate can contain explicit margins; compare the source core only.
            with wave.open(str(path),'rb') as stream:
                if (stream.getframerate(),stream.getnchannels(),stream.getsampwidth())!=(16000,1,2):
                    raise ValueError('Invalid candidate WAV format: '+clip['id'])
                audio=np.frombuffer(stream.readframes(stream.getnframes()),dtype='<i2').astype(np.float32)/32768
            identity &= abs(len(audio)/16000-c['audio']['duration'])<=.001
            shift=(c['start']+manifest['offset_ms']/1000-c['converted_start'])
            if c['conversion_job']!=job_id:
                repair=next(j for j in vc.queue(args) if j['id']==c['conversion_job'])
                repair_report=json.loads((batch/'reports'/(repair['id']+'.json')).read_text())
                parent=next(x for x in repair['clips'] if x['id']==clip['id'])
                shift=parent['start']+repair_report['timing']['median_lag_ms']/1000-c['converted_start']
            y=audio[max(0,round(shift*16000)):round((shift+clip['end']-clip['start'])*16000)]
            x=source[round(clip['start']*16000):round(clip['end']*16000)]
            rows.append(compare_clip(clip,x,y))
        export_hash=vc.digest(batch/'exports'/job['export_name'])
    else:
        report=vc.inspect_export(args)
        timing=report['timing'];identity=report['duration_within_100ms']
        export_hash=report['export_sha256']
        converted=page_audio
        offset=timing.get('median_lag_ms',0)/1000
        rows=[]
        for clip in job['clips']:
            x=source[round(clip['start']*16000):round(clip['end']*16000)]
            y=converted[round((clip['start']+offset)*16000):round((clip['end']+offset)*16000)]
            rows.append(compare_clip(clip,x,y))
    result={'job':job_id,'variant':variant,'export_sha256':export_hash,
        'manifest_sha256':vc.digest(folder/'manifest.json') if variant else None,
        'scope':'new conversion loss and file identity only; old corpus issues deferred',
        'passed':bool(identity and not passthrough and timing['stable'] and not any(r['new_loss'] for r in rows)),
        'untreated_input_suspected':bool(passthrough),
        'file_integrity':bool(identity),'timing':timing,'checked':len(rows),
        'new_loss':[r for r in rows if r['new_loss']],
        'inherited_silence':[r['id'] for r in rows if r['source_silent']],
        'phonetic_or_listening_review':False,'clips':rows}
    suffix='__'+variant if variant else ''
    vc.write_json(batch/'reports'/(job_id+suffix+'__conversion-integrity.json'),result)
    print(json.dumps({k:v for k,v in result.items() if k not in {'clips','timing'}},ensure_ascii=False))
    return result


def compare_clip(clip, source, converted):
    before=vc.boundary_metrics(source)
    after=vc.boundary_metrics(converted)
    missing=lost_speech(source,converted) if not before['silent_or_invalid'] else []
    truncated=len(converted)<len(source)-320
    new_loss=not before['silent_or_invalid'] and (after['silent_or_invalid'] or bool(missing) or truncated)
    return {'id':clip['id'],'text':clip.get('text',''),'source_start':clip['start'],
        'source_end':clip['end'],'source_silent':bool(before['silent_or_invalid']),
        'converted_silent':bool(after['silent_or_invalid']),'missing_intervals':missing,
        'truncated':truncated,'new_loss':bool(new_loss)}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--batch',type=Path,required=True);p.add_argument('--job',required=True)
    p.add_argument('--variant');a=p.parse_args();review(a.batch,a.job,a.variant)
