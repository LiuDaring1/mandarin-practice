"""Fixed expected/opposite pinyin controls on published learner annotations.

All six pure n/ng errors in the explored external corpus are retained, with
two deterministic normal controls each. Neither selection nor decisions read
acoustic classifier outputs. This is research, not a production diagnosis.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from ise_interphonic_preflight import PROVIDER, check_ledger, interphonic_word, sha
from ise_probe import IseProbe, parameters, public_result, target_at
from prepare_nasal_feature_data import interval
from suntone_probe import private_json


BASE = Path('data/derived/nasal-acoustic-validation')
FOLDER = BASE/'ise-pinyin-pairs-v1'
DATASET = BASE/'griffith-external-v2/dataset.json'


def opposite_pinyin(value):
    match = re.fullmatch(r'([a-z]+)([0-9])', value)
    if not match:
        raise ValueError('Expected a numbered ISE reference syllable')
    body, tone = match.groups()
    if body.endswith('ng'):
        return body[:-1] + tone
    if body.endswith('n'):
        return body + 'g' + tone
    raise ValueError('Reference syllable has no n/ng contrast')


def select_controls(rows):
    """Keep all pure errors; prefer same speaker/final, never read API outcomes."""
    errors = sorted([r for r in rows if r.get('pure_nasal_pair')], key=lambda r: r['id'])
    normals = [r for r in rows if r['state'] == 'normal_annotation'
               and r['label_source'] == 'published_consensus_no_segmental_error']
    selected = []; used = set()
    for error in errors:
        selected.append({**error, 'role': 'error', 'matched_error_id': error['id']})
        pool = [r for r in normals if r['expected_final'] == error['expected_final'] and r['id'] not in used]
        pool.sort(key=lambda r: (r['speaker'] != error['speaker'],
                                r['nominal_pinyin'] != error['nominal_pinyin'],
                                r['reference'] == error['reference'],
                                hashlib.sha256(r['id'].encode()).hexdigest()))
        if len(pool) < 2:
            raise ValueError('Insufficient distinct same-final controls; do not silently substitute')
        for control in pool[:2]:
            used.add(control['id'])
            selected.append({**control, 'role': 'normal', 'matched_error_id': error['id'],
                             'same_speaker_as_error': control['speaker'] == error['speaker']})
    return selected


def cache_key(audio, reference, core):
    return hashlib.sha256(IseProbe.cache_namespace + json.dumps(
        parameters(reference, core), sort_keys=True, ensure_ascii=False
    ).encode() + Path(audio).read_bytes()).hexdigest()


def reference_symbols(result, text):
    if result['status'] != 'ok':
        raise ValueError('Missing plain cached result')
    chars = [c for c in text if '\u3400' <= c <= '\u9fff']
    nodes = [n for n in result['nodes'] if n['tag'] == 'syll' and 'syll_index' in n]
    if [n['content'] for n in nodes] != chars or [n['syll_index'] for n in nodes] != list(range(len(chars))):
        raise ValueError('Full reference character sequence does not match')
    symbols = [n.get('symbol', '') for n in nodes]
    interphonic_word(''.join(chars), symbols)
    return ''.join(chars), symbols


def observe(result, row, syllables):
    try:
        text, symbols = reference_symbols(result, row['reference'])
    except ValueError:
        return {'state': 'unavailable', 'reason': 'unusable_reference'}
    if symbols != syllables:
        return {'state': 'unavailable', 'reason': 'reference_override_not_honored'}
    observation = target_at(result, text, row['position'])
    bounds = interval(observation, row['audio'])
    return {'state': observation['state'], 'reference_honored': True,
            'bounds': bounds, 'target_observation': observation}


def compare_pair(expected, opposite):
    """A fixed differential rule, with an overlap check independent of labels."""
    usable = ('flagged', 'not_flagged')
    if any(o.get('state') not in usable or not o.get('bounds') for o in (expected, opposite)):
        return {'decision': 'unknown', 'reason': 'unusable_target'}
    left, right = expected['bounds']['syllable'], opposite['bounds']['syllable']
    if len(left) != 2 or len(right) != 2 or not left[0] < left[1] or not right[0] < right[1]:
        return {'decision': 'unknown', 'reason': 'invalid_interval'}
    overlap = max(0., min(left[1], right[1]) - max(left[0], right[0])) / min(left[1]-left[0], right[1]-right[0])
    if overlap < .5:
        return {'decision': 'unknown', 'reason': 'reference_dependent_alignment', 'syllable_overlap': overlap}
    states = (expected['state'], opposite['state'])
    decision = {('flagged', 'not_flagged'): 'change', ('not_flagged', 'flagged'): 'match'}.get(states, 'unknown')
    return {'decision': decision, 'reason': 'differential_flags' if decision != 'unknown' else 'same_flags',
            'syllable_overlap': overlap}


async def prepare():
    if FOLDER.exists():
        raise ValueError('Pinyin pair plan already exists')
    preflight = BASE/'ise-interphonic-preflight-v1/result.json'
    if not json.loads(preflight.read_text())['all_references_honored']:
        raise ValueError('Reference override preflight failed')
    source = json.loads(DATASET.read_text())
    rows = select_controls(source['rows'] + source['excluded'])
    if len(rows) != 18 or sum(r['role'] == 'error' for r in rows) != 6:
        raise ValueError('Expected all six pure errors and twelve controls')
    ledger = json.loads((PROVIDER/'requests.json').read_text())
    if len(ledger) != 447:
        raise ValueError('Expected cumulative ISE count 447')
    probe = IseProbe(PROVIDER); prepared = []; plain_sources = {}
    for row in rows:
        result = public_result(await probe.call(row['audio'], row['reference'], core=row['core']))
        plain = PROVIDER/'cache'/f"{cache_key(row['audio'], row['reference'], row['core'])}.json"
        plain_sources[str(plain)] = sha(plain)
        record = {**row, 'audio_sha256': sha(row['audio']),
                  'plain_observation': target_at(result, row['reference'], row['position'])}
        try:
            text, symbols = reference_symbols(result, row['reference'])
            if symbols[row['position']] != row['nominal_pinyin']:
                raise ValueError('Reference pinyin differs from published nominal reading')
            altered = symbols.copy(); altered[row['position']] = opposite_pinyin(symbols[row['position']])
            record['conditions'] = []
            for name, values in [('expected', symbols), ('opposite', altered)]:
                reference = interphonic_word(text, values)
                record['conditions'].append({'name': name, 'reference': reference, 'pinyin': values,
                    'key': cache_key(row['audio'], reference, row['core'])})
        except ValueError as exc:
            record['conditions'] = []
            record['preparation_failure'] = str(exc)
        prepared.append(record)
    keys = sorted({c['key'] for r in prepared for c in r['conditions']})
    if not keys or len(keys) > 36:
        raise ValueError('Unexpected request count')
    new_keys = [k for k in keys if not (PROVIDER/'cache'/f'{k}.json').exists()]
    paths = [DATASET, preflight, Path(__file__), Path('scripts/ise_interphonic_preflight.py'),
             Path('scripts/ise_probe.py'), Path('scripts/suntone_probe.py'), Path('scripts/prepare_nasal_feature_data.py')]
    FOLDER.mkdir()
    private_json(FOLDER/'plan.json', {'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
        'sources': {str(p): sha(p) for p in paths}, 'plain_sources': plain_sources, 'rows': prepared,
        'request_keys': keys, 'new_request_keys': new_keys, 'ledger_prefix': ledger,
        'maximum_additional_attempts': len(new_keys), 'maximum_total_attempts': len(ledger)+len(new_keys),
        'selection': 'All 6 pure errors; 2 distinct same-final normal labels each; same-speaker then same-pinyin preference, fixed SHA order.',
        'rule': 'expected flagged/opposite unflagged => change; inverse => match; otherwise unknown; both valid and >=50% syllable overlap required.',
        'same_hanzi_in_both_conditions': True, 'punctuation_removed_in_both_conditions': True,
        'expected_and_opposite_tone_identical': True, 'new_training': False,
        'previously_explored_corpus': True, 'production_enabled': False,
        'limits': ['Only six pure substitutions in an already explored corpus.',
                   'Most controls cannot match the error speaker; same final is always required.',
                   'Pinyin reference symbols are not recognized actual speech.',
                   'General vowel-error flags need not isolate nasal-tail error.',
                   'No live microphone, noise, omission or repetition validation.']})
    print('ISE PAIR PLAN FROZEN',len(prepared),'targets;',len(new_keys),'maximum new calls; cap',len(ledger)+len(new_keys), flush=True)


def checked():
    plan = json.loads((FOLDER/'plan.json').read_text())
    for path, digest in {**plan['sources'], **plan['plain_sources']}.items():
        if sha(path) != digest:
            raise ValueError('Frozen pair source changed')
    for row in plan['rows']:
        if sha(row['audio']) != row['audio_sha256']:
            raise ValueError('Frozen pair audio changed')
        for c in row['conditions']:
            if cache_key(row['audio'], c['reference'], row['core']) != c['key']:
                raise ValueError('Frozen pair request changed')
    return plan


def summarize(rows):
    summaries = {}
    for role in ('error', 'normal'):
        for direction in ('all', 'front', 'back'):
            part = [r for r in rows if r['role'] == role and (direction == 'all' or r['expected_label'] == direction)]
            summaries[role+'_'+direction] = {'targets': len(part), **{
                name: sum(r['pair']['decision'] == name for r in part) for name in ('change', 'match', 'unknown')},
                'plain_flagged': sum(r['plain_state'] == 'flagged' for r in part),
                'explicit_expected_flagged': sum(r.get('observations', {}).get('expected', {}).get('state') == 'flagged' for r in part)}
    return summaries


async def run(allow_paid=False):
    plan = checked(); output = FOLDER/'result.json'
    if output.exists():
        raise ValueError('Pinyin pair result already frozen')
    check_ledger(plan['ledger_prefix'], json.loads((PROVIDER/'requests.json').read_text()), plan['new_request_keys'])
    probe = IseProbe(PROVIDER, allow_paid=allow_paid, max_calls=plan['maximum_total_attempts'])
    results = []
    for row in plan['rows']:
        observations = {}; caches = {}
        for c in row['conditions']:
            result = public_result(await probe.call(row['audio'], c['reference'], core=row['core']))
            observations[c['name']] = observe(result, row, c['pinyin'])
            caches[c['key']] = sha(PROVIDER/'cache'/f"{c['key']}.json")
            private_json(FOLDER/'current-target.json', {'id': row['id'], 'observations': observations, 'cache_sha256': caches})
            if result['status'] != 'ok':
                raise RuntimeError('Provider failure; stopped without retry')
        paired = compare_pair(observations.get('expected', {}), observations.get('opposite', {}))
        record = {k: row[k] for k in ('id', 'role', 'expected_label', 'actual_label')}
        record.update(plain_state=row['plain_observation']['state'], observations=observations,
                      pair=paired, cache_sha256=caches)
        results.append(record)
        private_json(FOLDER/'progress.json', {'rows': results})
        print('ISE PAIRED',len(results),'/',len(plan['rows']),row['role'],row['expected_label'],paired['decision'], flush=True)
    checked()
    ledger = json.loads((PROVIDER/'requests.json').read_text())
    new = check_ledger(plan['ledger_prefix'], ledger, plan['new_request_keys'])
    private_json(output, {'complete': True, 'plan_sha256': sha(FOLDER/'plan.json'), 'rows': results,
        'summary': summarize(results), 'additional_attempts': new, 'total_attempts': len(ledger),
        'previously_explored_corpus': True, 'production_enabled': False})
    print('ISE PAIR EXPERIMENT COMPLETE',json.dumps(summarize(results)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['prepare','run'])
    parser.add_argument('--allow-paid', action='store_true'); args = parser.parse_args()
    asyncio.run(prepare() if args.mode == 'prepare' else run(args.allow_paid))
