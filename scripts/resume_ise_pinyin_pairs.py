"""Finish frozen distinct requests; preserve both observed input-level failures.

A 3.67-second PCM16 recording returned 60114 although its plain-text request
had succeeded. Record the code without assuming the audio really was too long.
No failed identity is retried. Original plans, scripts and failed runs remain.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

import probe_ise_pinyin_pairs as original
from ise_probe import IseProbe, public_result
from suntone_probe import private_json


def input_failure(result):
    return result.get('status') == 'provider_error' and result.get('code') in (48195, 60114)


def prepare():
    plan = original.checked(); path = original.FOLDER/'recovery-plan.json'
    if path.exists(): raise ValueError('Recovery plan already frozen')
    sources = [Path(__file__),original.FOLDER/'continuation-plan.json',
               original.FOLDER/'continuation-progress.json',original.FOLDER/'continuation-failure.json']
    failures = {}
    for key in plan['request_keys']:
        cache = original.PROVIDER/'cache'/f'{key}.json'
        if cache.exists():
            result = public_result(json.loads(cache.read_text()))
            if result['status'] != 'ok':
                if not input_failure(result): raise ValueError('Unexplained global/transport failure')
                failures[str(cache)] = original.sha(cache)
    if len(failures) != 2: raise ValueError('Expected the two observed failures')
    private_json(path, {'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'original_plan_sha256':original.sha(original.FOLDER/'plan.json'),
        'sources':{str(p):original.sha(p) for p in sources},'failure_caches':failures,
        'allowed_codes':[48195,60114], 'maximum_total_attempts':plan['maximum_total_attempts'],
        'rule':'Keep per-request 48195/60114 unavailable, never retry, continue distinct frozen identities. Other failures stop.',
        'audio_for_60114_seconds':3.667375,'plain_reference_for_same_audio_succeeded':True,
        'diagnosis_of_60114_cause':'Not established; code alone does not prove this short waveform exceeds any real duration limit.',
        'denominator_unchanged':18,'selection_parameters_labels_and_decision_rule_unchanged':True})
    print('ISE PAIR RECOVERY FROZEN; no failed request retry',flush=True)


def checked():
    plan=original.checked(); recovery=json.loads((original.FOLDER/'recovery-plan.json').read_text())
    if recovery['original_plan_sha256']!=original.sha(original.FOLDER/'plan.json'):
        raise ValueError('Original plan changed')
    for path,digest in {**recovery['sources'],**recovery['failure_caches']}.items():
        if original.sha(path)!=digest:raise ValueError('Recovery source/failure changed')
    return plan


async def run(allow_paid=False):
    plan=checked();output=original.FOLDER/'resumed-result.json'
    if output.exists():raise ValueError('Recovery result already frozen')
    original.check_ledger(plan['ledger_prefix'],json.loads((original.PROVIDER/'requests.json').read_text()),plan['new_request_keys'])
    probe=IseProbe(original.PROVIDER,allow_paid=allow_paid,max_calls=plan['maximum_total_attempts']);rows=[]
    for row in plan['rows']:
        observations={};caches={};failures=[]
        for c in row['conditions']:
            result=public_result(await probe.call(row['audio'],c['reference'],core=row['core']))
            cache=original.PROVIDER/'cache'/f"{c['key']}.json";caches[c['key']]=original.sha(cache)
            observations[c['name']]=original.observe(result,row,c['pinyin'])
            if result['status']!='ok':
                failures.append({'key':c['key'],**result})
                if not input_failure(result):
                    private_json(original.FOLDER/'recovery-failure.json',{'id':row['id'],'result':result})
                    raise RuntimeError('New global/transport/unclassified failure; stopped without retry')
        pair=original.compare_pair(observations.get('expected',{}),observations.get('opposite',{}))
        record={k:row[k] for k in ('id','role','expected_label','actual_label')}
        record.update(plain_state=row['plain_observation']['state'],observations=observations,
                      pair=pair,cache_sha256=caches,provider_failures=failures)
        rows.append(record);private_json(original.FOLDER/'recovery-progress.json',{'rows':rows})
        print('ISE PAIR RESUMED',len(rows),'/',len(plan['rows']),row['role'],row['expected_label'],pair['decision'],flush=True)
    checked();ledger=json.loads((original.PROVIDER/'requests.json').read_text())
    new=original.check_ledger(plan['ledger_prefix'],ledger,plan['new_request_keys'])
    failures={f['key']:f for r in rows for f in r['provider_failures']}
    private_json(output,{'complete':True,'plan_sha256':original.sha(original.FOLDER/'plan.json'),
        'recovery_plan_sha256':original.sha(original.FOLDER/'recovery-plan.json'),
        'rows':rows,'summary':original.summarize(rows),'additional_attempts':new,'total_attempts':len(ledger),
        'unique_failed_requests':len(failures),'provider_error_codes':[f['code'] for f in failures.values()],
        'original_failed_runs_preserved':True,'previously_explored_corpus':True,'production_enabled':False})
    print('ISE PAIR RECOVERY COMPLETE',json.dumps(original.summarize(rows)),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','run'])
    parser.add_argument('--allow-paid',action='store_true');args=parser.parse_args()
    if args.mode=='prepare':prepare()
    else:asyncio.run(run(args.allow_paid))
