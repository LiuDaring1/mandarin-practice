"""Locate weak candidates using existing ISE cache files only.

No probe/network call, credential read, model score selection or actual-label
assignment. A usable interval or unflagged API result is not a correct label.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from inventory_eduhk_unmarked import FOLDER, sha
from ise_probe import IseProbe, parameters, public_result, target_at
from prepare_nasal_feature_data import interval
from train_nasal_feature_probe import save_json


def cache_path(audio, reference, core, directory):
    params = parameters(reference, core)
    key = hashlib.sha256(IseProbe.cache_namespace+json.dumps(params, sort_keys=True, ensure_ascii=False).encode()+audio).hexdigest()
    return Path(directory)/'cache'/f'{key}.json'


def main():
    plan_path = FOLDER/'alignment-plan.json'; output = FOLDER/'alignment.json'
    if plan_path.exists() or output.exists():
        raise ValueError('Weak alignment inventory already started')
    plan = json.loads((FOLDER/'plan.json').read_text())
    for path, digest in plan['sources'].items():
        if sha(path)!=digest:
            raise ValueError('Frozen inventory source changed')
    manifest = json.loads((FOLDER/'inventory.json').read_text())
    if manifest.get('complete') is not True or manifest['plan_sha256']!=sha(FOLDER/'plan.json'):
        raise ValueError('Incomplete/stale weak inventory')
    ledger = Path('data/derived/ise-validation/requests.json'); before = ledger.read_bytes()
    sources = [Path(__file__), FOLDER/'plan.json', FOLDER/'inventory.json', Path('scripts/ise_probe.py'),
               Path('scripts/prepare_nasal_feature_data.py')]
    save_json(plan_path, {'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
        'sources': {str(p): sha(p) for p in sources}, 'ledger_sha256': sha(ledger),
        'online_requests_permitted': False, 'credential_access': False, 'actual_labels_assigned': False,
        'flagged_target_policy': 'Retain flag as metadata; do not treat score as actual pronunciation truth.'})
    results = {}; cache_sources = {}; available = []; excluded = []
    for row in manifest['selected']:
        if row['split']!='train' or row['label_status']!='unverified' or 'actual_label' in row:
            raise ValueError('Weak source has changed its split or acquired a gold label')
        key = (row['audio'], row['reference'], row['core'])
        if key not in results:
            audio = Path(row['audio']).read_bytes()
            if hashlib.sha256(audio).hexdigest()!=row['audio_sha256']:
                raise ValueError('Input audio changed')
            path = cache_path(audio, row['reference'], row['core'], ledger.parent)
            if path.exists():
                raw = path.read_bytes(); cache_sources[str(path)] = hashlib.sha256(raw).hexdigest()
                results[key] = public_result(json.loads(raw))
            else:
                results[key] = {'status': 'not_cached'}
        result = results[key]
        observation = target_at(result, row['reference'], row['position'])
        bounds = interval(observation, row['audio'])
        if bounds is None:
            excluded.append({**row, 'reason': 'uncached_alignment' if result['status']=='not_cached' else 'unusable_cached_interval',
                             'api_state': observation['state']})
        else:
            available.append({**row, 'bounds': bounds, 'api_state': observation['state'], 'alignment_reviewed_by_human': False})
    if ledger.read_bytes()!=before:
        raise ValueError('API ledger changed during cache-only inventory')
    report = {'complete': True, 'plan_sha256': sha(plan_path), 'rows': available, 'excluded': excluded,
        'selected_targets': len(manifest['selected']), 'recordings': len(results), 'cached_recordings': len(cache_sources),
        'cache_sources': cache_sources, 'api_states': dict(Counter(r['api_state'] for r in available+excluded)),
        'api_requests': 0, 'ledger_count': len(json.loads(before)), 'ledger_unchanged': True,
        'actual_labels_assigned': False,
        'limits': ['API flags and alignment availability cannot certify unmarked pronunciations as correct.',
                   'All selected targets, including rejected/uncached ones, remain in the inventory.']}
    save_json(output, report)
    print('CACHE ALIGNMENT', len(available), 'available', len(excluded), 'excluded', len(cache_sources), 'cached recordings',
          json.dumps(report['api_states']), 'ledger', report['ledger_count'], flush=True)


if __name__=='__main__':
    main()
