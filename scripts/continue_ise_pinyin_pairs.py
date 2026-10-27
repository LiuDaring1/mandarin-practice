"""Continue untouched pair requests after a recorded reference-format failure.

The original failed run and its frozen source/plan stay unchanged. A known
48195 reference-format rejection is retained as unavailable, never retried;
authentication, transport and other provider failures still stop the batch.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

import probe_ise_pinyin_pairs as original
from ise_probe import IseProbe, public_result
from suntone_probe import private_json


def permitted_format_failure(result):
    return result.get('status') == 'provider_error' and result.get('code') == 48195


def prepare():
    plan = original.checked(); path = original.FOLDER/'continuation-plan.json'
    if path.exists():
        raise ValueError('Continuation plan already frozen')
    failures = {}
    for key in plan['request_keys']:
        cache = original.PROVIDER/'cache'/f'{key}.json'
        if cache.exists():
            result = public_result(json.loads(cache.read_text()))
            if result['status'] != 'ok':
                if not permitted_format_failure(result):
                    raise ValueError('Failure is not an isolated reference-format rejection')
                failures[str(cache)] = original.sha(cache)
    if not failures:
        raise ValueError('No known reference-format failure to continue past')
    private_json(path, {'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
        'original_plan_sha256': original.sha(original.FOLDER/'plan.json'),
        'sources': {str(p): original.sha(p) for p in [Path(__file__),
            original.FOLDER/'progress.json', original.FOLDER/'current-target.json']},
        'known_failure_caches': failures, 'allowed_provider_error': 48195,
        'policy': 'Retain 48195 as unavailable and continue other distinct frozen requests; no retry or new request identity.',
        'reason': 'Original batch stopped on bian4 to biang4 reference. Official code 48195 denotes a test-paper format error; this is not evidence of quota/auth failure.',
        'documentation': 'https://www.xfyun.cn/doc/Ise/IseAPI.html',
        'denominator_unchanged': 18, 'maximum_total_attempts': plan['maximum_total_attempts'],
        'no_changes_to_selection_labels_parameters_or_decision_rule': True})
    print('ISE PAIR CONTINUATION FROZEN; original failures preserved', flush=True)


def checked():
    plan = original.checked(); amendment = json.loads((original.FOLDER/'continuation-plan.json').read_text())
    if amendment['original_plan_sha256'] != original.sha(original.FOLDER/'plan.json'):
        raise ValueError('Original pair plan changed')
    for path, digest in {**amendment['sources'], **amendment['known_failure_caches']}.items():
        if original.sha(path) != digest:
            raise ValueError('Original failure or continuation source changed')
    return plan


async def run(allow_paid=False):
    plan = checked(); output = original.FOLDER/'continued-result.json'
    if output.exists():
        raise ValueError('Continued pair result already frozen')
    original.check_ledger(plan['ledger_prefix'], json.loads((original.PROVIDER/'requests.json').read_text()), plan['new_request_keys'])
    probe = IseProbe(original.PROVIDER, allow_paid=allow_paid, max_calls=plan['maximum_total_attempts'])
    rows = []
    for row in plan['rows']:
        observations = {}; caches = {}; failures = []
        for condition in row['conditions']:
            result = public_result(await probe.call(row['audio'], condition['reference'], core=row['core']))
            cache = original.PROVIDER/'cache'/f"{condition['key']}.json"
            caches[condition['key']] = original.sha(cache)
            observations[condition['name']] = original.observe(result, row, condition['pinyin'])
            if result['status'] != 'ok':
                failures.append({k: result[k] for k in ('status','code','error_type','http_status') if k in result})
                if not permitted_format_failure(result):
                    private_json(original.FOLDER/'continuation-failure.json', {'id': row['id'], 'result': result})
                    raise RuntimeError('New non-format failure; stopped without retry')
        paired = original.compare_pair(observations.get('expected', {}), observations.get('opposite', {}))
        record = {k: row[k] for k in ('id','role','expected_label','actual_label')}
        record.update(plain_state=row['plain_observation']['state'], observations=observations,
                      pair=paired, cache_sha256=caches, format_failures=failures)
        rows.append(record)
        private_json(original.FOLDER/'continuation-progress.json', {'rows': rows})
        print('ISE PAIR CONTINUED', len(rows), '/', len(plan['rows']),row['role'],row['expected_label'],paired['decision'], flush=True)
    checked()
    ledger = json.loads((original.PROVIDER/'requests.json').read_text())
    new = original.check_ledger(plan['ledger_prefix'], ledger, plan['new_request_keys'])
    private_json(output, {'complete':True,'plan_sha256':original.sha(original.FOLDER/'plan.json'),
        'continuation_plan_sha256':original.sha(original.FOLDER/'continuation-plan.json'),
        'rows':rows,'summary':original.summarize(rows),'additional_attempts':new,'total_attempts':len(ledger),
        'format_error_attempts':sum(len(r['format_failures']) for r in rows),
        'original_failed_run_preserved':True,'previously_explored_corpus':True,'production_enabled':False})
    print('ISE PAIR CONTINUATION COMPLETE', json.dumps(original.summarize(rows)),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','run'])
    parser.add_argument('--allow-paid',action='store_true');args=parser.parse_args()
    if args.mode=='prepare':prepare()
    else:asyncio.run(run(args.allow_paid))
