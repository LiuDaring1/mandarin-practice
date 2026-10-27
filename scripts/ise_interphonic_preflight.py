"""Four-call ISE reference-format preflight, isolated from student diagnosis.

Returned symbols describe the reference, not recognized speech. These source
recordings are protocol controls, not newly human-verified learner labels.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from ise_probe import IseProbe, parameters, public_result, target_at
from suntone_probe import private_json


FOLDER = Path('data/derived/nasal-acoustic-validation/ise-interphonic-preflight-v1')
PROVIDER = Path('data/derived/ise-validation')
DOCUMENTATION = 'https://www.xfyun.cn/doc/Ise/IseAPI.html'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def interphonic_word(text, syllables):
    """Encode one word; callers must separately verify dictionary syllables."""
    if not text or len(text) > 100 or any(not '\u4e00' <= c <= '\u9fff' for c in text):
        raise ValueError('Preflight words must contain only simplified-range Han characters')
    if len(syllables) != len(text) or any(not re.fullmatch(r'[a-z]+[0-9]', s) for s in syllables):
        raise ValueError('Exactly one explicit numbered pinyin per character is required')
    return '<customizer: interphonic>\n' + text + '\n' + '|'.join(syllables)


def request_key(audio, reference):
    return hashlib.sha256(IseProbe.cache_namespace + json.dumps(
        parameters(reference, 'read_word'), sort_keys=True, ensure_ascii=False
    ).encode() + Path(audio).read_bytes()).hexdigest()


def inspect_reference(result, text, syllables):
    """Require complete ordered reference parity before interpreting a target."""
    if result['status'] != 'ok':
        return {'state': 'unavailable', 'reference_honored': False}
    nodes = [n for n in result['nodes'] if n['tag'] == 'syll' and 'syll_index' in n]
    chars = [n['content'] for n in nodes]
    symbols = [n.get('symbol') for n in nodes]
    honored = chars == list(text) and symbols == list(syllables) and [n['syll_index'] for n in nodes] == list(range(len(text)))
    observation = target_at(result, text, 0) if honored else {'state': 'reference_mismatch', 'finals': []}
    return {'state': observation['state'], 'reference_honored': honored,
            'returned_characters': chars, 'returned_reference_symbols': symbols,
            'target_observation': observation,
            'recognized_pronunciation_available': False}


def check_ledger(prefix, ledger, allowed_keys):
    if ledger[:len(prefix)] != prefix or len(ledger) > len(prefix) + len(allowed_keys):
        raise ValueError('ISE cumulative ledger changed outside the frozen allowance')
    added = ledger[len(prefix):]
    if len(set(added)) != len(added) or any(key not in allowed_keys for key in added):
        raise ValueError('Unexpected ISE call in the preflight interval')
    return len(added)


async def prepare():
    from validate_ise_stability import prepare_cells
    if FOLDER.exists():
        raise ValueError('Preflight plan already exists')
    ledger = json.loads((PROVIDER/'requests.json').read_text())
    if len(ledger) != 443:
        raise ValueError('Expected original cumulative ledger count of 443')
    cells = {c['source_text']: c for c in prepare_cells(PROVIDER)
             if c['kind'] == 'word_context' and not c['cross_reference']}
    probe = IseProbe(PROVIDER)
    rows = []
    baseline = []
    for text, original in [('林业', ('lin2', 'ye4')), ('零件', ('ling2', 'jian4'))]:
        cell = cells[text]
        key = request_key(cell['audio'], text)
        cached = PROVIDER/'cache'/f'{key}.json'
        result = public_result(await probe.call(cell['audio'], text, core='read_word'))
        observation = inspect_reference(result, text, original)
        if not observation['reference_honored']:
            raise ValueError('Plain cached reference does not match expected reading')
        baseline.append({'text': text, 'pinyin': original, 'cache': str(cached),
                         'cache_sha256': sha(cached), 'inspection': observation})
        for first in (original[0], 'ling2' if original[0] == 'lin2' else 'lin2'):
            syllables = (first, original[1])
            reference = interphonic_word(text, syllables)
            rows.append({'text': text, 'pinyin': syllables, 'audio': cell['audio'],
                         'audio_sha256': sha(cell['audio']), 'reference': reference,
                         'request_key': request_key(cell['audio'], reference),
                         'core': 'read_word', 'opposite_reference': first != original[0]})
    if len({r['request_key'] for r in rows}) != 4:
        raise ValueError('Expected four distinct protocol cells')
    FOLDER.mkdir()
    private_json(FOLDER/'plan.json', {
        'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
        'documentation': DOCUMENTATION, 'rows': rows, 'plain_cached_controls': baseline,
        'ledger_prefix': ledger, 'maximum_additional_attempts': 4, 'maximum_total_attempts': 447,
        'sources': {str(p): sha(p) for p in map(Path, [
            'scripts/ise_interphonic_preflight.py', 'scripts/ise_probe.py', 'scripts/suntone_probe.py'])},
        'new_recordings': False, 'learner_accuracy_experiment': False,
        'returned_symbols_are_reference_not_recognition': True,
        'failure_policy': 'Cache every attempt; stop on provider/transport failure; never automatically retry.',
        'production_enabled': False,
    })
    print('ISE INTERPHONIC PLAN FROZEN: 4 calls; cumulative cap 447', flush=True)


def checked():
    plan = json.loads((FOLDER/'plan.json').read_text())
    for path, digest in plan['sources'].items():
        if sha(path) != digest:
            raise ValueError('Frozen preflight source changed')
    for row in plan['rows']:
        if sha(row['audio']) != row['audio_sha256'] or request_key(row['audio'], row['reference']) != row['request_key']:
            raise ValueError('Frozen preflight audio/reference changed')
    for row in plan['plain_cached_controls']:
        if sha(row['cache']) != row['cache_sha256']:
            raise ValueError('Original cached result changed')
    return plan


async def run(allow_paid=False):
    plan = checked()
    output = FOLDER/'result.json'
    if output.exists():
        raise ValueError('Preflight result is already frozen')
    keys = [r['request_key'] for r in plan['rows']]
    check_ledger(plan['ledger_prefix'], json.loads((PROVIDER/'requests.json').read_text()), keys)
    probe = IseProbe(PROVIDER, allow_paid=allow_paid, max_calls=plan['maximum_total_attempts'])
    rows = []
    for cell in plan['rows']:
        result = public_result(await probe.call(cell['audio'], cell['reference'], core=cell['core']))
        inspection = inspect_reference(result, cell['text'], cell['pinyin'])
        row = {k: cell[k] for k in ('text', 'pinyin', 'opposite_reference', 'request_key')}
        row.update(status=result['status'], inspection=inspection,
                   cache_sha256=sha(PROVIDER/'cache'/f"{cell['request_key']}.json"))
        rows.append(row)
        private_json(FOLDER/'progress.json', {'rows': rows})
        print(json.dumps({'text': cell['text'], 'reference_pinyin': cell['pinyin'],
                          'reference_honored': inspection['reference_honored'],
                          'target_state': inspection['state']}, ensure_ascii=False), flush=True)
        if result['status'] != 'ok':
            raise RuntimeError('Provider/transport failure; stopped without retry')
    checked()
    ledger = json.loads((PROVIDER/'requests.json').read_text())
    additional = check_ledger(plan['ledger_prefix'], ledger, keys)
    private_json(output, {'complete': True, 'plan_sha256': sha(FOLDER/'plan.json'),
                         'rows': rows, 'additional_attempts': additional,
                         'total_attempts': len(ledger),
                         'all_references_honored': all(r['inspection']['reference_honored'] for r in rows),
                         'learner_accuracy_experiment': False, 'production_enabled': False})
    print('ISE INTERPHONIC PREFLIGHT COMPLETE', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'run'])
    parser.add_argument('--allow-paid', action='store_true')
    args = parser.parse_args()
    asyncio.run(prepare() if args.mode == 'prepare' else run(args.allow_paid))
