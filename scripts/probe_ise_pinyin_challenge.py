"""Frozen ISE challenge: published normal targets already flagged by the API.

This intentionally selected hard set cannot estimate population accuracy. All
mixed nasal substitutions are also retained. No new production policy or fit.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path

from pypinyin.constants import PINYIN_DICT
from pypinyin.contrib.tone_convert import to_normal

import probe_ise_pinyin_pairs as prior
from ise_probe import IseProbe, public_result, target_at
from resume_ise_pinyin_pairs import input_failure
from suntone_probe import private_json


FOLDER = prior.BASE/'ise-pinyin-challenge-v1'
TEMPORAL = prior.BASE/'hubert-temporal-v1'


def dictionary_bodies():
    return sorted({to_normal(p).replace('ü','v') for code, values in PINYIN_DICT.items()
                   if 0x4e00 <= code <= 0x9fff for p in values.split(',')})


def dictionary_identity():
    return {'pypinyin':importlib.metadata.version('pypinyin'),
            'sha256':hashlib.sha256(json.dumps(dictionary_bodies()).encode()).hexdigest()}


def select_challenge(rows):
    selected=[]
    for row in rows:
        normal=(row['state']=='normal_annotation' and row.get('api_state')=='flagged'
                and row.get('label_source')=='published_consensus_no_segmental_error'
                and row['actual_label']==row['expected_label'])
        mixed=(row['state']=='nasal_substitution' and row.get('pure_nasal_pair') is False
               and row.get('label_source')=='explicit_suffix_substitution'
               and row['actual_label']!=row['expected_label'])
        if normal or mixed:
            selected.append({**row,'role':'normal' if normal else 'error',
                             'selection_reason':'prior_api_false_alarm' if normal else 'mixed_segmental_nasal_error'})
    if len({r['id'] for r in selected})!=len(selected):raise ValueError('Duplicate challenge target')
    return sorted(selected,key=lambda r:r['id'])


def merged_decision(api, local, mode):
    """Fixed diagnostics; matches require two matches, disagreements abstain."""
    allowed=('change','match','unknown')
    if api not in allowed or local not in allowed:raise ValueError('Unknown decision')
    if mode=='api':return api
    if mode=='local':return local
    if mode=='agreement':return api if api==local else 'unknown'
    if mode!='correction_union':raise ValueError('Unknown comparison mode')
    if set((api,local))=={'change','match'}:return 'unknown'
    if 'change' in (api,local):return 'change'
    return 'match' if api==local=='match' else 'unknown'


async def prepare():
    if FOLDER.exists():raise ValueError('Challenge plan already exists')
    dataset=json.loads(prior.DATASET.read_text());rows=select_challenge(dataset['rows']+dataset['excluded'])
    if Counter(r['role'] for r in rows)!=Counter({'normal':10,'error':7}):raise ValueError('Expected 17 frozen challenge targets')
    previous=json.loads((prior.FOLDER/'resumed-result.json').read_text())
    if not previous['complete'] or {r['id'] for r in rows}&{r['id'] for r in previous['rows']}:
        raise ValueError('Prior batch incomplete or challenge overlaps previous selection')
    ledger=json.loads((prior.PROVIDER/'requests.json').read_text())
    if len(ledger)!=478:raise ValueError('Expected cumulative ISE count 478')
    probe=IseProbe(prior.PROVIDER);prepared=[];caches={};vocabulary=set(dictionary_bodies())
    for row in rows:
        result=public_result(await probe.call(row['audio'],row['reference'],core=row['core']))
        path=prior.PROVIDER/'cache'/f"{prior.cache_key(row['audio'],row['reference'],row['core'])}.json"
        caches[str(path)]=prior.sha(path)
        observed=target_at(result,row['reference'],row['position'])
        if observed['state']!=row['api_state']:raise ValueError('Cached plain state changed')
        record={**row,'audio_sha256':prior.sha(row['audio']),'plain_observation':observed,'conditions':[]}
        try:
            text,symbols=prior.reference_symbols(result,row['reference'])
            if symbols[row['position']]!=row['nominal_pinyin']:
                raise ValueError('Reference pinyin differs from published nominal reading')
            altered=symbols.copy();altered[row['position']]=prior.opposite_pinyin(symbols[row['position']])
            if any(v[:-1] not in vocabulary for v in symbols+altered):
                raise ValueError('Reference contains a syllable absent from the pinned basic-Han dictionary')
            for name,values in [('expected',symbols),('opposite',altered)]:
                reference=prior.interphonic_word(text,values)
                record['conditions'].append({'name':name,'reference':reference,'pinyin':values,
                    'key':prior.cache_key(row['audio'],reference,row['core'])})
        except ValueError as exc:record['preparation_failure']=str(exc)
        prepared.append(record)
    keys=sorted({c['key'] for r in prepared for c in r['conditions']})
    new=[];existing={}
    for key in keys:
        path=prior.PROVIDER/'cache'/f'{key}.json'
        if path.exists():existing[str(path)]=prior.sha(path)
        else:new.append(key)
    if not new or len(new)>34:raise ValueError('Unexpected new request count')
    sources=[prior.DATASET,prior.FOLDER/'plan.json',prior.FOLDER/'resumed-result.json',
        TEMPORAL/'selection.json',TEMPORAL/'evaluation.json',Path(__file__),
        Path('scripts/probe_ise_pinyin_pairs.py'),Path('scripts/ise_interphonic_preflight.py'),
        Path('scripts/ise_probe.py'),Path('scripts/suntone_probe.py'),
        Path('scripts/prepare_nasal_feature_data.py'),Path('scripts/resume_ise_pinyin_pairs.py')]
    FOLDER.mkdir()
    private_json(FOLDER/'plan.json',{'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'sources':{str(p):prior.sha(p) for p in sources},'plain_cache_sources':caches,
        'existing_condition_caches':existing,'dictionary':dictionary_identity(),
        'rows':prepared,'request_keys':keys,'new_request_keys':new,'ledger_prefix':ledger,
        'maximum_additional_attempts':len(new),'maximum_total_attempts':len(ledger)+len(new),
        'selection_is_api_conditioned_challenge':True,'population_accuracy_estimate':False,
        'previously_explored_corpus':True,'new_training':False,'production_enabled':False,
        'decision_rule':'Unchanged paired flags, full reference adoption, valid bounds and >=50% syllable overlap.',
        'comparison_modes':['api','local','agreement','correction_union'],
        'union_policy':'Any change with no competing match; matches require both; otherwise unknown.',
        'compare_datasets':['new challenge 17','prior 18 plus new 17; intentionally sampled, not population'],
        'failure_policy':'48195 and 60114 remain unavailable; other failures stop; cached failures never retried.',
        'dictionary_limit':'Basic-Han syllable presence is only a local syntax guard, not a guarantee of provider support.'})
    print('ISE CHALLENGE FROZEN',len(prepared),'targets;',len(new),'new requests; cap',len(ledger)+len(new),flush=True)


def checked():
    plan=json.loads((FOLDER/'plan.json').read_text())
    if dictionary_identity()!=plan['dictionary']:raise ValueError('Pinyin dictionary changed')
    for path,digest in {**plan['sources'],**plan['plain_cache_sources'],**plan['existing_condition_caches']}.items():
        if prior.sha(path)!=digest:raise ValueError('Frozen challenge source changed')
    for r in plan['rows']:
        if prior.sha(r['audio'])!=r['audio_sha256']:raise ValueError('Challenge audio changed')
        for c in r['conditions']:
            if prior.cache_key(r['audio'],c['reference'],r['core'])!=c['key']:raise ValueError('Challenge request changed')
    return plan


async def run(allow_paid=False):
    plan=checked();output=FOLDER/'result.json'
    if output.exists():raise ValueError('Challenge result already frozen')
    prior.check_ledger(plan['ledger_prefix'],json.loads((prior.PROVIDER/'requests.json').read_text()),plan['new_request_keys'])
    probe=IseProbe(prior.PROVIDER,allow_paid=allow_paid,max_calls=plan['maximum_total_attempts']);rows=[]
    for r in plan['rows']:
        observations={};caches={};failures=[]
        for c in r['conditions']:
            result=public_result(await probe.call(r['audio'],c['reference'],core=r['core']))
            cache=prior.PROVIDER/'cache'/f"{c['key']}.json";caches[c['key']]=prior.sha(cache)
            observations[c['name']]=prior.observe(result,r,c['pinyin'])
            if result['status']!='ok':
                failures.append({'key':c['key'],**result})
                if not input_failure(result):
                    private_json(FOLDER/'stopped.json',{'id':r['id'],'result':result})
                    raise RuntimeError('Unclassified provider/transport failure; no automatic retry')
        paired=prior.compare_pair(observations.get('expected',{}),observations.get('opposite',{}))
        record={k:r[k] for k in ('id','role','expected_label','actual_label','selection_reason')}
        record.update(plain_state=r['plain_observation']['state'],pair=paired,observations=observations,
                      cache_sha256=caches,provider_failures=failures)
        rows.append(record);private_json(FOLDER/'progress.json',{'rows':rows})
        print('ISE CHALLENGE',len(rows),'/',len(plan['rows']),r['role'],r['expected_label'],paired['decision'],flush=True)
    checked();ledger=json.loads((prior.PROVIDER/'requests.json').read_text())
    added=prior.check_ledger(plan['ledger_prefix'],ledger,plan['new_request_keys'])
    failures={f['key']:f for r in rows for f in r['provider_failures']}
    private_json(output,{'complete':True,'plan_sha256':prior.sha(FOLDER/'plan.json'),'rows':rows,
        'summary':prior.summarize(rows),'additional_attempts':added,'total_attempts':len(ledger),
        'provider_failed_requests':len(failures),'provider_error_codes':[f['code'] for f in failures.values()],
        'selection_is_api_conditioned_challenge':True,'population_accuracy_estimate':False})
    print('ISE CHALLENGE COMPLETE',json.dumps(prior.summarize(rows)),flush=True)


def audit():
    plan=checked();output=FOLDER/'comparison.json'
    if output.exists():raise ValueError('Challenge comparison already frozen')
    current=json.loads((FOLDER/'result.json').read_text());previous=json.loads((prior.FOLDER/'resumed-result.json').read_text())
    local={r['id']:r for r in json.loads((TEMPORAL/'evaluation.json').read_text())['comparison']['primary']['griffith']['predictions']}
    reports={}
    for name,rows in [('challenge',current['rows']),('combined',previous['rows']+current['rows'])]:
        reports[name]={}
        for mode in plan['comparison_modes']:
            results=[]
            for r in rows:
                pred=local.get(r['id'],{});local_decision='change' if pred.get('candidate_nasal_change') else 'match' if pred.get('candidate_nasal_match') else 'unknown'
                decision=merged_decision(r['pair']['decision'],local_decision,mode)
                results.append({**r,'pair':{'decision':decision},'local_decision':local_decision})
            reports[name][mode]={'summary':prior.summarize(results),
                'rows':[{'id':r['id'],'role':r['role'],'expected_label':r['expected_label'],
                         'decision':r['pair']['decision'],'local_decision':r['local_decision']} for r in results]}
    private_json(output,{'complete':True,'plan_sha256':prior.sha(FOLDER/'plan.json'),
        'result_sha256':prior.sha(FOLDER/'result.json'),'comparisons':reports,
        'models_and_rules_frozen_before_challenge':True,'no_policy_selected_from_these_results':True,
        'population_accuracy_estimate':False,'production_enabled':False})
    for name,methods in reports.items():
        for mode,report in methods.items():
            print('CHALLENGE COMPARISON',name,mode,json.dumps({k:report['summary'][k] for k in ('error_all','normal_all')}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','run','audit'])
    parser.add_argument('--allow-paid',action='store_true');args=parser.parse_args()
    if args.mode=='audit':audit()
    else:asyncio.run(prepare() if args.mode=='prepare' else run(args.allow_paid))
