"""Run a manifest of research targets with a cumulative 200-attempt ceiling.

Continued research is authorized by the user's standing goal. This is a new
bounded experiment, not a reset of the existing ledger. Each run may add at most
100 requests, and existing equivalent requests are always read from cache.
"""
import argparse
import asyncio
import json
from pathlib import Path

from ise_probe import IseProbe, public_result, target_at
from suntone_probe import private_json


async def run(args):
    cases = json.loads(Path(args.input).read_text())['cases']
    folder = Path('data/derived/ise-validation')
    ledger = folder / 'requests.json'
    before = len(json.loads(ledger.read_text()))
    probe = IseProbe(folder, allow_paid=args.allow_paid, max_calls=min(200, before + 100))
    rows = []
    output = Path(args.output)
    consecutive_failures = set()
    for case in cases:
        result = public_result(await probe.call(case['audio'], case['reference'], core=case['core']))
        observation = target_at(result, case['reference'], case['position'])
        row = {k: v for k, v in case.items() if k != 'audio'}
        row.update(ise_status=result['status'], ise_observation=observation)
        if result['status'] != 'ok':
            row['ise_failure'] = {k: result[k] for k in ('status', 'code', 'error_type', 'http_status') if k in result}
        rows.append(row)
        private_json(output, {'complete': False, 'ledger_before': before, 'cases': rows})
        print(case['id'], case['reference'], observation['state'], flush=True)
        if result['status'] != 'ok':
            consecutive_failures.add((case['audio'], case['reference'], case['core']))
            if not args.continue_on_unavailable or len(consecutive_failures) >= 3:
                raise RuntimeError('Provider failure: batch stopped without retry')
        else:
            consecutive_failures.clear()
    after = len(json.loads(ledger.read_text()))
    private_json(output, {'complete': True, 'ledger_before': before, 'ledger_after': after,
                          'new_calls': after - before, 'cases': rows})
    print('COMPLETE targets', len(rows), 'new_calls', after - before, 'ledger_total', after, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--allow-paid', action='store_true')
    parser.add_argument('--continue-on-unavailable', action='store_true',
                        help='Keep cached failures as unknown and try other recordings; stop after 3 distinct consecutive failures. Never retry a failed request.')
    asyncio.run(run(parser.parse_args()))
