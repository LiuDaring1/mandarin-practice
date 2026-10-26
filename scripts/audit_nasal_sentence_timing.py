"""Compare sentence target timing with a second fixed aligner.

Agreement is only a timing consistency check, never proof of pronunciation.
This audit does not replace, filter or relabel the frozen training dataset.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from prepare_eduhk_crops import ALIGNER_REVISION
from train_nasal_feature_probe import save_json


def character_interval(items,reference,position,duration):
    chars=''.join(c for c in reference if '\u3400'<=c<='\u9fff')
    if len(items)!=len(chars) or any(len(t['text'])!=1 for t in items) or ''.join(t['text'] for t in items)!=chars:
        return None
    if not 0<=position<len(chars):
        return None
    item=items[position];start,end=item['start'],item['end']
    if not 0<=start<end<=duration+.01 or not .08<=end-start<=2.:
        return None
    return [start,end]


def compare_intervals(api,other):
    if api is None or other is None:
        return {'state':'unavailable'}
    if not api[0]<api[1] or not other[0]<other[1]:
        return {'state':'unavailable'}
    overlap=max(0.,min(api[1],other[1])-max(api[0],other[0]))
    fraction=overlap/min(api[1]-api[0],other[1]-other[0])
    center_delta=abs(sum(api)/2-sum(other)/2)
    return {'state':'timing_conflict' if overlap<=0 or fraction<.3 or center_delta>.25 else 'consistent',
            'overlap_shorter_fraction':fraction,'center_delta_seconds':center_delta}


def align(folder):
    from mlx_audio.stt.utils import load_model
    manifest=json.loads((folder/'input.json').read_text())
    cache=folder/'independent-alignments';cache.mkdir(exist_ok=True)
    model=None;records=[]
    for rec in manifest['records']:
        audio_sha=hashlib.sha256(Path(rec['audio']).read_bytes()).hexdigest()
        text=''.join(c for c in rec['reference'] if '\u3400'<=c<='\u9fff')
        key=hashlib.sha256((audio_sha+text+ALIGNER_REVISION+'sentence-timing-v1').encode()).hexdigest()
        path=cache/(key+'.json')
        if not path.exists():
            if model is None:
                model=load_model(Path.home()/'.cache/huggingface/hub/models--mlx-community--Qwen3-ForcedAligner-0.6B-8bit/snapshots'/ALIGNER_REVISION)
            result=model.generate(rec['audio'],text=text,language='Chinese')
            items=[{'text':r.text,'start':r.start_time,'end':r.end_time} for r in result.items]
            save_json(path,{'key':key,'audio_sha256':audio_sha,'model_revision':ALIGNER_REVISION,
                            'reference_chars':text,'items':items})
        records.append({'uid':rec['uid'],'cache':str(path),'audio_sha256':audio_sha})
        print('aligned',rec['uid'],flush=True)
    save_json(folder/'independent-alignment-index.json',{'complete':True,'records':records,
               'thresholds':{'max_center_delta_seconds':.25,'min_overlap_shorter_fraction':.3,
                             'min_target_duration':.08,'max_target_duration':2.},
               'limits':['Reference-conditioned timing, not pronunciation classification.',
                         'No human boundary certification and no dataset filtering.']})


def compare(folder):
    output=folder/'timing-audit.json'
    if output.exists():
        raise ValueError('Timing comparison is frozen')
    manifest=json.loads((folder/'input.json').read_text())
    index=json.loads((folder/'independent-alignment-index.json').read_text())
    if index.get('complete') is not True:
        raise ValueError('Independent alignment is incomplete')
    cache={r['uid']:json.loads(Path(r['cache']).read_text()) for r in index['records']}
    dataset=json.loads((folder/'dataset.json').read_text());by_id={r['id']:r for r in dataset['rows']}
    rows=[]
    for rec in manifest['records']:
        stored=cache[rec['uid']]
        if hashlib.sha256(Path(rec['audio']).read_bytes()).hexdigest()!=stored['audio_sha256']:
            raise ValueError('Audio changed after alignment')
        for target in rec['targets']:
            uid=rec['uid']+'-pos'+str(target['position']);existing=by_id.get(uid)
            independent=character_interval(stored['items'],rec['reference'],target['position'],rec['duration'])
            api=existing['bounds']['syllable'] if existing else None
            rows.append({'id':uid,'split':rec['split'],'api':api,'independent':independent,
                         'independent_usable':independent is not None,**compare_intervals(api,independent)})
    report={'complete':True,'rows':rows,'states':dict(Counter(r['state'] for r in rows)),
            'independent_usable':sum(r['independent_usable'] for r in rows),
            'thresholds':index['thresholds'],'dataset_changed_by_audit':False}
    save_json(output,report)
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['align','compare'])
    parser.add_argument('--directory',default='data/derived/nasal-acoustic-validation/context-training-v4')
    args=parser.parse_args()
    (align if args.mode=='align' else compare)(Path(args.directory))
