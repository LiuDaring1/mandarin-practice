"""Free-transcript target-location audit, deliberately blind to nasal correctness.

Front/back nasal pairs are folded ONLY while locating a target in the transcript.
The ASR transcript is never used as a pronunciation label or positive diagnosis.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from pypinyin import lazy_pinyin,Style
from prepare_eduhk_crops import ASR_REVISION
from train_nasal_feature_probe import save_json


def fold_nasal(syllable):
    return syllable[:-1] if syllable.endswith(('ang','eng','ing')) else syllable


def edit_table(reference,observed):
    table=[[0]*(len(observed)+1) for _ in range(len(reference)+1)]
    for i in range(len(reference)+1):table[i][0]=i
    for j in range(len(observed)+1):table[0][j]=j
    for i,left in enumerate(reference,1):
        for j,right in enumerate(observed,1):
            table[i][j]=min(table[i-1][j]+1,table[i][j-1]+1,table[i-1][j-1]+(left!=right))
    return table


def locate_targets(reference,observed):
    """Keep all optimal alignments; repeated tokens must not be guessed."""
    forward=edit_table(reference,observed)
    reverse=edit_table(reference[::-1],observed[::-1])
    m,n=len(reference),len(observed);distance=forward[m][n]
    backward=lambda i,j:reverse[m-i][n-j]
    rows=[]
    for i,token in enumerate(reference):
        matches=[j for j,other in enumerate(observed) if token==other
                 and forward[i][j]+backward(i+1,j+1)==distance]
        can_delete=any(forward[i][j]+1+backward(i+1,j)==distance for j in range(n+1))
        can_substitute=any(token!=other and forward[i][j]+1+backward(i+1,j+1)==distance
                           for j,other in enumerate(observed))
        state='unique_match' if len(matches)==1 and not can_delete and not can_substitute else 'ambiguous' if matches else 'not_matched'
        rows.append({'position':i,'state':state,'possible_observed_positions':matches,
                     'deletion_is_optimal':can_delete,'substitution_is_optimal':can_substitute})
    return {'edit_distance':distance,'reference_tokens':m,'observed_tokens':n,'targets':rows}


def main(folder):
    from opencc import OpenCC
    from mlx_audio.stt.utils import load_model
    converter=OpenCC('tw2s')
    manifest=json.loads((folder/'input.json').read_text())
    cache=folder/'free-transcripts';cache.mkdir(exist_ok=True)
    output=folder/'content-audit.json'
    if output.exists():raise ValueError('Free transcript audit is frozen')
    model=None;rows=[];records=[]
    for rec in manifest['records']:
        sha=hashlib.sha256(Path(rec['audio']).read_bytes()).hexdigest()
        key=hashlib.sha256((sha+ASR_REVISION+'chinese-temp0-max512-free-v1').encode()).hexdigest()
        path=cache/(key+'.json')
        if not path.exists():
            if model is None:
                model=load_model(Path.home()/'.cache/huggingface/hub/models--mlx-community--Qwen3-ASR-1.7B-8bit/snapshots'/ASR_REVISION)
            result=model.generate(rec['audio'],language='Chinese',max_tokens=512,temperature=0)
            save_json(path,{'audio_sha256':sha,'model_revision':ASR_REVISION,'reference_prompt':False,'text':result.text})
        text=json.loads(path.read_text())['text']
        observed=''.join(c for c in converter.convert(text) if '\u3400'<=c<='\u9fff')
        reference=''.join(c for c in rec['reference'] if '\u3400'<=c<='\u9fff')
        ref=[fold_nasal(p) for p in lazy_pinyin(reference,style=Style.NORMAL)]
        spoken=[fold_nasal(p) for p in lazy_pinyin(observed,style=Style.NORMAL)]
        alignment=locate_targets(ref,spoken)
        for target in rec['targets']:
            mapping=alignment['targets'][target['position']]
            rows.append({'id':rec['uid']+'-pos'+str(target['position']),'split':rec['split'],**mapping})
        records.append({'uid':rec['uid'],'cache':str(path),**{k:alignment[k] for k in ['edit_distance','reference_tokens','observed_tokens']}})
        print(rec['uid'],'targets checked',len(rec['targets']),'edit distance',alignment['edit_distance'],flush=True)
    save_json(output,{'complete':True,'rows':rows,'records':records,'states':dict(Counter(r['state'] for r in rows)),
                      'reference_prompt':False,'nasal_pair_folding_for_location_only':True,
                      'limits':['ASR errors can look like omissions; uncertain location is not proof the learner omitted a word.',
                                'An ASR match never certifies the target nasal pronunciation.',
                                'No automatic data filtering or label changes.']})
    print('COMPLETE',dict(Counter(r['state'] for r in rows)),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--directory',default='data/derived/nasal-acoustic-validation/context-training-v4')
    args=parser.parse_args();main(Path(args.directory))
