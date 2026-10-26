"""Annotation-only inventory with target mappings shared by ALL best alignments.

Do not zip unequal token sequences. A target is eligible only if every minimum
unit-edit path maps it to the same actual token, with no equally good deletion.
Other target substitutions are retained as exclusions, never normal labels.
"""
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path

from audit_latic_nasal_annotations import FOLDER as SOURCE,canonical,compare,read_notations
from nasal_acoustics import nasal_group
from probe_eduhk_nasal import model_final
from probe_nasal_pairs import sha
from train_nasal_feature_probe import save_json

FOLDER=SOURCE.parent/'latic-alignment-audit-v2'


def distances(left,right):
    rows=[[0]*(len(right)+1) for _ in range(len(left)+1)]
    rows[0]=list(range(len(right)+1))
    for i in range(1,len(left)+1):
        rows[i][0]=i
        for j in range(1,len(right)+1):
            rows[i][j]=min(rows[i-1][j]+1,rows[i][j-1]+1,rows[i-1][j-1]+(left[i-1]!=right[j-1]))
    return rows


def unique_mapping(expected,actual):
    """Return unique indices or None, retaining all optimal path possibilities."""
    left=[canonical(x) for x in expected];right=[canonical(x) for x in actual]
    forward=distances(left,right);reverse=distances(left[::-1],right[::-1])
    n,m=len(left),len(right);cost=forward[n][m];mapping=[]
    for i in range(n):
        possibilities=set()
        for j in range(m+1):
            if forward[i][j]+1+reverse[n-i-1][m-j]==cost: possibilities.add(None)
            if j<m and forward[i][j]+(left[i]!=right[j])+reverse[n-i-1][m-j-1]==cost:
                possibilities.add(j)
        if not possibilities: raise ValueError('Edit graph lost an expected token')
        mapping.append(next(iter(possibilities)) if len(possibilities)==1 and None not in possibilities else None)
    return mapping,cost


def inventory(expected,actual):
    try: mapping,cost=unique_mapping(expected,actual)
    except ValueError: return [],[],None,'unsupported_token'
    targets=[];excluded=[]
    for position,token in enumerate(expected):
        intended=canonical(token)
        if nasal_group(model_final(intended)) is None: continue
        actual_position=mapping[position]
        if actual_position is None:
            excluded.append({'token_position':position,'reason':'deleted_or_ambiguous_alignment'});continue
        candidate,reason=compare([token],[actual[actual_position]])
        if reason:
            excluded.append({'token_position':position,'actual_token_position':actual_position,'reason':reason});continue
        if len(candidate)!=1: raise ValueError('Nasal target disappeared')
        targets.append({**candidate[0],'token_position':position,'actual_token_position':actual_position})
    return targets,excluded,cost,None


def main():
    if FOLDER.exists(): raise ValueError('LATIC alignment inventory frozen')
    provenance=json.loads((SOURCE/'source.json').read_text())
    for row in provenance['sources']:
        if sha(SOURCE/row['name'])!=row['sha256']: raise ValueError('Annotation source changed')
    expected=read_notations(SOURCE/'suppose-notations.txt');actual=read_notations(SOURCE/'actual-notations.txt')
    strict=json.loads((SOURCE/'nasal-annotation-inventory.json').read_text())
    for path,digest in strict['sources'].items():
        if sha(path)!=digest: raise ValueError('Strict inventory source changed')
    records=[];excluded=[]
    for uid in sorted(set(expected)|set(actual)):
        if uid not in expected or uid not in actual:
            excluded.append({'id':uid,'reason':'unpaired_id'});continue
        targets,rejected,cost,reason=inventory(expected[uid],actual[uid])
        if reason: excluded.append({'id':uid,'reason':reason});continue
        records.append({'id':uid,'speaker':uid[1:5],'edit_distance':cost,'targets':targets,'excluded_targets':rejected,'audio_obtained':False})
    by_id={r['id']:r for r in records};replayed=0
    for old in strict['records']:
        fresh={t['token_position']:t for t in by_id[old['id']]['targets']}
        for target in old['targets']:
            if target['token_position'] not in fresh or any(fresh[target['token_position']][k]!=v for k,v in target.items()):
                raise ValueError('Previously strict target changed')
            replayed+=1
    targets=[t for r in records for t in r['targets']]
    counts={'utterances':len(records),'speakers':len({r['speaker'] for r in records}),
        'target_states':dict(Counter(t['state'] for t in targets)),
        'error_directions':dict(Counter(t['expected_label']+'->'+t['actual_label'] for t in targets if t['expected_label']!=t['actual_label'])),
        'excluded_target_reasons':dict(Counter(t['reason'] for r in records for t in r['excluded_targets'])),
        'excluded_utterances':len(excluded),'strict_targets_replayed':replayed}
    paths=[SOURCE/n for n in ('source.json','actual-notations.txt','suppose-notations.txt','nasal-annotation-inventory.json')]
    paths += [Path(__file__),Path('scripts/audit_latic_nasal_annotations.py'),Path('scripts/nasal_acoustics.py'),Path('scripts/probe_eduhk_nasal.py')]
    FOLDER.mkdir()
    save_json(FOLDER/'inventory.json',{'complete':True,'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'sources':{str(p):sha(p) for p in paths},'counts':counts,'records':records,'excluded':excluded,
        'alignment':'unit Levenshtein, identical target mapping in every globally optimal path',
        'audio_obtained':False,'used_for_training_or_evaluation':False,
        'limits':['Unique token alignment is not acoustic boundary or pronunciation validation.',
            'Pinyin token indices are not Chinese character positions.',
            'Other errors in an utterance are allowed; only exact unchanged or n/ng-only target spellings accepted.',
            'Four speakers; no independent multi-rater agreement asserted; no audio obtained.']})
    print('LATIC UNIQUE ALIGNMENT INVENTORY',json.dumps(counts),flush=True)


if __name__=='__main__': main()
