"""Recover the observed disk-disconnect interruption without resending calls.

The terminal acknowledged requests 1..10; request 11 may have been in flight.
Eight new responses were lost, one new request is conservatively reserved.
Missing responses stay unknown. No fabricated provider cache is written.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

import probe_same_tail_specificity as original
from ise_probe import IseProbe, public_result

FOLDER = original.FOLDER
MIRROR = Path.home()/'.cache/nasal-api-recovery/same-tail-specificity-v1'


def durable_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_suffix('.durable-tmp')
    fd = os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    os.fchmod(fd,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.flush();os.fsync(stream.fileno())
    temporary.replace(path)
    directory = os.open(path.parent,os.O_RDONLY)
    try: os.fsync(directory)
    finally: os.close(directory)


class MirroredIseProbe(IseProbe):
    async def evaluate(self,config,params,audio):
        # The parent already holds its file lock and has reserved this key.
        # Persist on the internal disk before sending any new network frame.
        key = hashlib.sha256(self.cache_namespace+json.dumps(params,sort_keys=True,ensure_ascii=False).encode()+audio).hexdigest()
        ledger = original.read(self.directory/'requests.json')
        if key not in ledger: raise ValueError('Request not reserved before send')
        MIRROR.mkdir(parents=True,exist_ok=True);MIRROR.chmod(0o700)
        durable_json(MIRROR/'requests.json',ledger)
        result = await super().evaluate(config,params,audio)
        durable_json(MIRROR/'cache'/(key+'.json'),result)
        return result


def prepare(baseline):
    original.checked(); path = FOLDER/'disk-recovery-plan.json'
    if path.exists(): raise ValueError('Recovery plan already frozen')
    prior = original.read(baseline); provider = original.paired.PROVIDER
    ledger = original.read(provider/'requests.json')
    if len(ledger)!=497 or ledger!=prior['ledger']: raise ValueError('Unexpected pre-recovery ledger')
    records = original.read(original.INPUT/'input.json')['records']
    requests = [{'audio':r['audio'],'reference':r['reference'],'core':r['core'],
        'key':original.paired.cache_key(r['audio'],r['reference'],r['core'])} for r in records]
    stage = original.stage_budget(requests,ledger,provider/'cache')
    if len(stage['new_request_keys'])!=15 or len(stage['existing_caches'])!=4:
        raise ValueError('Lost stage plan cannot be deterministically reconstructed')
    keys = [r['key'] for r in stage['requests']]
    missing = [k for k in keys[:11] if k in stage['new_request_keys']]
    confirmed = [k for k in keys[:10] if k in stage['new_request_keys']]
    if len(missing)!=9 or len(confirmed)!=8: raise ValueError('Unexpected interruption prefix')
    surviving = {str(p):original.paired.sha(p) for p in FOLDER.iterdir() if p.is_file()}
    if (FOLDER/'plain-plan.json').exists() or (FOLDER/'plain-progress.json').exists():
        raise ValueError('Unexpected surviving stage artifact; inspect first')
    reconstructed = {**stage,'main_plan_sha256':original.paired.sha(FOLDER/'plan.json')}
    MIRROR.mkdir(parents=True,exist_ok=True);MIRROR.chmod(0o700)
    durable_json(MIRROR/'main-plan.json',original.read(FOLDER/'plan.json'))
    durable_json(MIRROR/'plain-plan.json',reconstructed)
    durable_json(FOLDER/'plain-plan.json',reconstructed)
    plan = {'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'source_sha256':original.paired.sha(__file__),'main_plan_sha256':original.paired.sha(FOLDER/'plan.json'),
        'reconstructed_plain_plan_sha256':original.paired.sha(FOLDER/'plain-plan.json'),
        'surviving_files':surviving,'baseline':str(baseline),'baseline_sha256':original.paired.sha(baseline),
        'ledger_prefix':ledger,'confirmed_lost_response_keys':confirmed,
        'possibly_sent_request_keys':[keys[10]],'never_resend_keys':missing,
        'remaining_new_request_keys':[k for k in stage['new_request_keys'] if k not in missing],
        'terminal_evidence':{'session_id':59396,'exit_code':138,'completed_ordered_requests':10,
            'statuses':['ok','ok','provider_error','ok','ok','ok','ok','ok','ok','ok'],
            'third_request_provider_code':60114,'last_request_may_have_been_in_flight':11},
        'durability_loss':'Only main plan and zero-byte plain-plan.tmp survived; ledger reverted to 497 and new caches/progress disappeared.',
        'reconstructed_plan_limit':'Original stage-plan hash was not externally saved; reconstructed deterministically from surviving inputs, original 497 ledger and 4 original caches.',
        'ledger_accounting':'Reserve 8 terminal-confirmed sent keys and 1 possibly-sent key. The reservation count is an upper bound, not an exact billing count.',
        'api_parameters_or_decision_rules_changed':False,'missing_results':'Unknown, never fabricated or retried.',
        'reader_adapter':'Only paired preparation uses a reader accepting the 9 documented missing responses; all other original code remains unchanged.',
        'internal_mirror':str(MIRROR),'reconstructed_maximum_total_attempts':512}
    durable_json(MIRROR/'disk-recovery-plan.json',plan);durable_json(path,plan)
    reserved=ledger+missing
    durable_json(MIRROR/'requests.json',reserved);durable_json(provider/'requests.json',reserved)
    print('DISK RECOVERY FROZEN: 8 confirmed lost, 1 possible; 6 fresh requests remain; 506 reservations',flush=True)


def checked():
    original.checked(); plan=original.read(FOLDER/'disk-recovery-plan.json')
    if (plan['source_sha256']!=original.paired.sha(__file__) or
        plan['main_plan_sha256']!=original.paired.sha(FOLDER/'plan.json') or
        plan['reconstructed_plain_plan_sha256']!=original.paired.sha(FOLDER/'plain-plan.json') or
        plan['baseline_sha256']!=original.paired.sha(plan['baseline'])):
        raise ValueError('Recovery provenance changed')
    ledger=original.read(original.paired.PROVIDER/'requests.json')
    if ledger[:506]!=plan['ledger_prefix']+plan['never_resend_keys']:
        raise ValueError('Recovery reservations changed')
    return plan


async def resume(allow_paid=False):
    recovery=checked(); plan=original.checked_stage('plain'); provider=original.paired.PROVIDER
    output=FOLDER/'plain-result.json'
    if output.exists(): raise ValueError('Recovered plain result already frozen')
    original.paired.check_ledger(plan['ledger_prefix'],original.read(provider/'requests.json'),plan['new_request_keys'])
    probe=MirroredIseProbe(provider,allow_paid=allow_paid,max_calls=512); results={}
    for i,r in enumerate(plan['requests']):
        if r['key'] in recovery['never_resend_keys']:
            if (provider/'cache'/(r['key']+'.json')).exists(): raise ValueError('Unexpected cache for lost response')
            result={'status':'interrupted_missing_result'}
            results[r['key']]={'result':result,'cache_sha256':None,'disk_recovery_plan_sha256':original.paired.sha(FOLDER/'disk-recovery-plan.json')}
        else:
            result=public_result(await probe.call(r['audio'],r['reference'],core=r['core']))
            results[r['key']]={'result':result,'cache_sha256':original.paired.sha(provider/'cache'/(r['key']+'.json'))}
            if result['status']!='ok' and not original.input_failure(result):
                durable_json(FOLDER/'plain-recovery-failure.json',{'key':r['key'],'result':result})
                raise RuntimeError('New unexpected failure, no retry')
        durable_json(MIRROR/'plain-recovered-progress.json',{'results':results})
        durable_json(FOLDER/'plain-recovered-progress.json',{'results':results})
        print('SPECIFICITY RECOVERY',i+1,'/',len(plan['requests']),result['status'],flush=True)
    ledger=original.read(provider/'requests.json')
    added=original.paired.check_ledger(plan['ledger_prefix'],ledger,plan['new_request_keys'])
    output_value={'complete':True,'stage_plan_sha256':original.paired.sha(FOLDER/'plain-plan.json'),
        'results':results,'additional_reservations':added,'total_reservations':len(ledger),
        'confirmed_new_calls_after_recovery':len(ledger)-506,
        'confirmed_new_calls_before_loss':8,'possibly_sent_before_loss':1,
        'missing_response_requests':9,'disk_recovery_plan_sha256':original.paired.sha(FOLDER/'disk-recovery-plan.json'),
        'provider_failed_requests_with_recovered_cache':sum(v['result']['status']=='provider_error' for v in results.values())}
    durable_json(MIRROR/'plain-result.json',output_value);durable_json(output,output_value)
    print('SPECIFICITY RECOVERY COMPLETE reservations',len(ledger),'new calls range',added-1,added,flush=True)


def recovered_plain(name):
    if name!='plain': raise ValueError('Recovery reader is only for the interrupted plain stage')
    recovery=checked(); original.checked_stage('plain'); result=original.read(FOLDER/'plain-result.json')
    if (not result['complete'] or result['stage_plan_sha256']!=original.paired.sha(FOLDER/'plain-plan.json') or
        result['disk_recovery_plan_sha256']!=original.paired.sha(FOLDER/'disk-recovery-plan.json')):
        raise ValueError('Recovered result provenance changed')
    missing=set()
    for key,value in result['results'].items():
        if value['result']['status']=='interrupted_missing_result':
            if (value['cache_sha256'] is not None or key not in recovery['never_resend_keys'] or
                value['disk_recovery_plan_sha256']!=original.paired.sha(FOLDER/'disk-recovery-plan.json')):
                raise ValueError('Undocumented missing response')
            missing.add(key)
        elif original.paired.sha(original.paired.PROVIDER/'cache'/(key+'.json'))!=value['cache_sha256']:
            raise ValueError('Recovered cache changed')
    if missing!=set(recovery['never_resend_keys']): raise ValueError('Missing-response denominator changed')
    return result


def prepare_pairs():
    # Explicit dependency adapter; preserves the original pairing and exclusion
    # logic byte-for-byte, including all 24 targets in the denominator.
    old_reader=original.read_stage_result
    try:
        original.read_stage_result=recovered_plain
        original.prepare_pairs()
    finally: original.read_stage_result=old_reader
    for name in ('dataset.json','pairs-plan.json'):
        durable_json(MIRROR/name,original.read(FOLDER/name))


async def run_pairs(allow_paid=False):
    checked();old_probe=original.IseProbe
    try:
        original.IseProbe=MirroredIseProbe
        await original.run_stage('pairs',allow_paid)
    finally: original.IseProbe=old_probe
    durable_json(MIRROR/'pairs-result.json',original.read(FOLDER/'pairs-result.json'))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','resume','pairs-prepare','pairs'])
    parser.add_argument('--baseline',type=Path);parser.add_argument('--allow-paid',action='store_true');args=parser.parse_args()
    if args.mode=='prepare':
        if args.baseline is None:parser.error('--baseline required')
        prepare(args.baseline)
    elif args.mode=='pairs-prepare':prepare_pairs()
    else:asyncio.run(resume(args.allow_paid) if args.mode=='resume' else run_pairs(args.allow_paid))
