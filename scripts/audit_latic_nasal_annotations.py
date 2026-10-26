"""Inventory public actual/target annotations; no audio or accuracy claims.

Only equal-length sequences that differ exclusively by nasal coda spelling
are accepted. Other substitutions, insertion/deletion and unclear tags keep
the whole utterance outside this conservative candidate inventory.
"""
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import re

from nasal_acoustics import nasal_group
from probe_eduhk_nasal import model_final
from probe_nasal_pairs import sha
from train_nasal_feature_probe import save_json

FOLDER=Path('data/derived/nasal-acoustic-validation/latic-source-audit-v1')


def canonical(value):
    if not re.fullmatch(r'[a-z]+[0-5]',value): raise ValueError('Unclear or unsupported phonetic token')
    syllable=value[:-1]
    # j/q/x/y conventionally omit the dots of ü. Other u/v distinctions stay.
    return re.sub(r'^([jqxy])v',r'\1u',syllable)


def compare(expected,actual):
    if len(expected)!=len(actual):return [],'unequal_token_count'
    try:a=[canonical(v) for v in expected];b=[canonical(v) for v in actual]
    except ValueError:return [],'unsupported_token'
    for first,second in zip(a,b):
        if first!=second and not ((first.endswith('n') and second==first+'g') or (second.endswith('n') and first==second+'g')):
            return [],'other_segmental_change'
    targets=[]
    for position,(first,second) in enumerate(zip(a,b)):
        intended=nasal_group(model_final(first));spoken=nasal_group(model_final(second))
        if intended is None:continue
        if spoken is None:raise ValueError('Pure coda comparison lost actual nasal label')
        targets.append({'token_position':position,'expected_pinyin':first,'actual_pinyin':second,
            'expected_label':intended,'actual_label':spoken,'state':'normal_notation' if first==second else 'pure_nasal_substitution_notation'})
    return targets,None


def read_notations(path):
    rows={}
    for line in path.read_text().splitlines():
        if not line.strip():continue
        fields=line.split(maxsplit=1)
        if len(fields)!=2 or not re.fullmatch(r'\d{9}',fields[0]):raise ValueError('Malformed annotation identity')
        uid,tokens=fields
        if uid in rows:raise ValueError('Duplicate annotation identity')
        if uid[1:5] not in ('0010','0011','0012','0013'):raise ValueError('Unexpected corpus speaker')
        rows[uid]=tokens.split()
    return rows


def main():
    output=FOLDER/'nasal-annotation-inventory.json'
    if output.exists():raise ValueError('LATIC annotation inventory frozen')
    source=json.loads((FOLDER/'source.json').read_text())
    for row in source['sources']:
        if sha(FOLDER/row['name'])!=row['sha256']:raise ValueError('Pinned annotation source changed')
    expected=read_notations(FOLDER/'suppose-notations.txt');actual=read_notations(FOLDER/'actual-notations.txt')
    rows=[];excluded=[]
    for uid in sorted(set(expected)|set(actual)):
        if uid not in expected or uid not in actual:
            excluded.append({'id':uid,'reason':'unpaired_annotation_id'});continue
        targets,reason=compare(expected[uid],actual[uid])
        if reason:excluded.append({'id':uid,'reason':reason});continue
        rows.append({'id':uid,'speaker':uid[1:5],'targets':targets,'audio_obtained':False})
    targets=[t for r in rows for t in r['targets']]
    counts={'expected_utterances':len(expected),'actual_utterances':len(actual),'accepted_utterances':len(rows),
        'speakers':len({r['speaker'] for r in rows}),'excluded_utterances':len(excluded),
        'target_states':dict(Counter(t['state'] for t in targets)),
        'error_directions':dict(Counter(t['expected_label']+'->'+t['actual_label'] for t in targets if t['expected_label']!=t['actual_label'])),
        'excluded_reasons':dict(Counter(r['reason'] for r in excluded))}
    save_json(output,{'complete':True,'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'sources':{str(p):sha(p) for p in (FOLDER/'source.json',Path(__file__),Path('scripts/probe_eduhk_nasal.py'),Path('scripts/nasal_acoustics.py'))},
        'counts':counts,'records':rows,'excluded':excluded,'audio_obtained':False,'used_for_training_or_evaluation':False,
        'limits':['Annotation inventory only; no local audio matching, boundary verification, provider calls or scoring.',
            'Four speakers only. No claim of independent multi-rater agreement per target.',
            'Target positions are pinyin-token positions, not yet mapped to Chinese characters.',
            'Strict entire-sequence filtering excludes other errors; it is not complete corpus error coverage.']})
    print('LATIC ANNOTATION INVENTORY',json.dumps(counts),flush=True)


if __name__=='__main__':main()
