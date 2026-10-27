"""Resume the interrupted fixed cohort without resending unresolved requests.

The original request plan remains immutable. During calls, the authoritative
ledger and raw responses live on the internal disk. The external provider lock
is held for the batch; a prefix-checked publication restores external copies.
"""
import argparse
import asyncio
import fcntl
import json
import os
from pathlib import Path

import run_matrix_validation as run
from ise_probe import public_result
from nasal_validation_execution import MirroredIseProbe, align_target, durable_json
from probe_ise_pinyin_pairs import cache_key, check_ledger
from resume_ise_pinyin_pairs import input_failure


def publish_file(source, destination):
    data=source.read_bytes();destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists() and destination.read_bytes()!=data:raise ValueError('Different existing artifact: '+destination.name)
    with destination.open('wb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
        if hasattr(fcntl,'F_FULLFSYNC'):fcntl.fcntl(stream,fcntl.F_FULLFSYNC)
    destination.chmod(0o600)


def save(name,value):
    durable_json(run.MIRROR/name,value);publish_file(run.MIRROR/name,run.FOLDER/name)


def partition(plan, ledger, cache):
    check_ledger(plan['ledger_prefix'],ledger,plan['new_request_keys'])
    completed=[];unresolved=[];remaining=[]
    for r in plan['requests']:
        if (cache/(r['key']+'.json')).exists():completed.append(r['key'])
        elif r['key'] in ledger:unresolved.append(r['key'])
        else:remaining.append(r['key'])
    return {'completed_keys':completed,'unresolved_keys':unresolved,'remaining_keys':remaining}


def prepare():
    plan=run.api_checked();run.new('resume-plan.json')
    provider=run.MIRROR/'provider';ledger=run.runtime.read(provider/'requests.json')
    groups=partition(plan,ledger,provider/'cache')
    event=run.runtime.read(run.MIRROR/'recovery-event.json')
    if groups['unresolved_keys']!=event['unresolved_reserved_keys']:raise ValueError('Recovery uncertainty changed')
    publish_file(run.PROVIDER/'config.json',provider/'config.json')
    save('resume-plan.json',{'api_plan_sha256':run.runtime.sha(run.FOLDER/'api-plan.json'),
        'recovery_event_sha256':run.runtime.sha(run.MIRROR/'recovery-event.json'),'ledger_checkpoint':ledger,
        **groups,'source':str(Path(__file__).resolve()),'source_sha256':run.runtime.sha(__file__),
        'unresolved_are_not_retried':True,'new_budget_added':0})
    print('RESUME PLAN', {k:len(v) for k,v in groups.items()},flush=True)


def checked():
    plan=run.api_checked();resume=run.runtime.read(run.MIRROR/'resume-plan.json')
    if (resume['api_plan_sha256']!=run.runtime.sha(run.FOLDER/'api-plan.json') or
        resume['source_sha256']!=run.runtime.sha(resume['source']) or
        resume['recovery_event_sha256']!=run.runtime.sha(run.MIRROR/'recovery-event.json')):
        raise ValueError('Resume provenance changed')
    return plan,resume


def publish_provider():
    provider=run.MIRROR/'provider';ledger=run.runtime.read(provider/'requests.json');old=run.runtime.read(run.PROVIDER/'requests.json')
    if ledger[:len(old)]!=old:raise ValueError('External ledger diverged; do not overwrite')
    for source in (provider/'cache').glob('*.json'):publish_file(source,run.PROVIDER/'cache'/source.name)
    # Ledger is the sole intentionally mutable artifact, after prefix validation.
    durable_json(run.PROVIDER/'requests.json',ledger)
    with (run.PROVIDER/'requests.json').open('rb') as stream:
        if hasattr(fcntl,'F_FULLFSYNC'):fcntl.fcntl(stream,fcntl.F_FULLFSYNC)


async def api(allow_paid=False):
    plan,resume=checked();run.new('api-result.json');provider=run.MIRROR/'provider'
    lock=os.open(run.PROVIDER/'probe.lock',os.O_CREAT|os.O_RDWR,0o600)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        old=run.runtime.read(run.PROVIDER/'requests.json');ledger=run.runtime.read(provider/'requests.json')
        if ledger[:len(old)]!=old or ledger[:len(resume['ledger_checkpoint'])]!=resume['ledger_checkpoint']:
            raise ValueError('Ledger diverged')
        current=partition(plan,ledger,provider/'cache')
        if current['unresolved_keys']!=resume['unresolved_keys']:
            raise ValueError('Another interrupted request; audit before resuming')
        probe=MirroredIseProbe(provider,mirror=run.MIRROR/'provider-secondary',allow_paid=allow_paid,max_calls=plan['maximum_total_attempts'])
        results={}
        for i,r in enumerate(plan['requests']):
            if r['key'] in resume['unresolved_keys']:continue
            result=public_result(await probe.call(r['audio'],r['reference'],core=r['core']))
            results[r['key']]={'result':result,'cache_sha256':run.runtime.sha(provider/'cache'/(r['key']+'.json'))}
            durable_json(run.MIRROR/'resume-progress.json',{'results':results})
            if result['status']!='ok' and not input_failure(result):raise RuntimeError('Unclassified failure; inspect, never retry')
            print('MATRIX RESUME',i+1,'/',len(plan['requests']),result['status'],flush=True)
        ledger=run.runtime.read(provider/'requests.json')
        added=check_ledger(plan['ledger_prefix'],ledger,plan['new_request_keys'])
        publish_provider()
        save('api-result.json',{'complete':True,'api_plan_sha256':run.runtime.sha(run.FOLDER/'api-plan.json'),
            'resume_plan_sha256':run.runtime.sha(run.MIRROR/'resume-plan.json'),'results':results,
            'unresolved_keys':resume['unresolved_keys'],'new_reservations':added,
            'confirmed_new_responses':len(set(results)&set(plan['new_request_keys'])),
            'cumulative_reservations':len(ledger),'historical_possibly_sent_calls':1,
            'new_possibly_sent_calls':len(resume['unresolved_keys']),'production_enabled':False})
    finally:os.close(lock)


def align():
    checked();plan,content=run.imported();run.new('dataset.json');response=run.runtime.read(run.FOLDER/'api-result.json')
    if not response['complete'] or response['api_plan_sha256']!=run.runtime.sha(run.FOLDER/'api-plan.json'):raise ValueError('Response provenance changed')
    for key,value in response['results'].items():
        if run.runtime.sha(run.PROVIDER/'cache'/(key+'.json'))!=value['cache_sha256']:raise ValueError('Response changed')
    rows=[];excluded=[]
    for r,c in zip(plan['records'],content['rows']):
        key=cache_key(r['audio'],r['reference'],r['core'])
        for target in run.selected([r]):
            row={**target,**{k:r[k] for k in ('audio','audio_sha256','reference','core')}}
            if not c['identity_ok']:excluded.append({**row,'reason':'content_identity_mismatch'});continue
            if key in response['unresolved_keys']:
                excluded.append({**row,'reason':'reserved_request_without_response_after_interruption'});continue
            item,ok=align_target(row,response['results'][key]['result']);(rows if ok else excluded).append(item)
    if len(rows)+len(excluded)!=154:raise ValueError('Alignment lost targets')
    save('dataset.json',{'rows':rows,'excluded':excluded,'api_result_sha256':run.runtime.sha(run.FOLDER/'api-result.json')})
    print('MATRIX RECOVERED ALIGNMENT',len(rows),'available',len(excluded),'unavailable',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','api','align']);parser.add_argument('--allow-paid',action='store_true');args=parser.parse_args()
    if args.mode=='api':asyncio.run(api(args.allow_paid))
    else:globals()[args.mode]()
