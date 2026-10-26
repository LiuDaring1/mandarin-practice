"""Independent, human-annotated sentence controls and explicit nasal errors.

The archive remains private. No model predictions select recordings or labels.
NP is the nominal pronunciation, not a recognized pronunciation. Only explicit
unambiguous substitutions become errors; undecoded annotation is retained.
"""
import argparse
import asyncio
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import wave
from zipfile import ZipFile

from pypinyin import lazy_pinyin, Style
from nasal_acoustics import nasal_group
from probe_eduhk_nasal import model_final
from train_nasal_feature_probe import save_json

BASE = Path('data/derived/nasal-acoustic-validation/griffith')
SEED = 'griffith-independent-nasal-20261027-v1'


def annotation_label(nominal, error, miscellaneous=''):
    """Decode an explicit suffix replacement, refusing uncertain error syntax."""
    syllable = re.sub(r'[0-4]$', '', nominal.strip())
    expected = nasal_group(model_final(syllable))
    if expected is None or syllable.endswith('r'):
        return {'state': 'not_supported_nasal'}
    if miscellaneous.strip():
        return {'state': 'miscellaneous_annotation'}
    segment = re.sub(r'TT?[0-4]\{[0-4]\}', '', error).strip()
    common = {'expected_label': expected, 'expected_final': model_final(syllable)}
    if not segment:
        return {'state': 'normal_annotation', 'actual_label': expected,
                'label_source': 'published_consensus_no_segmental_error', **common}
    match = re.fullmatch(r'([a-z]+)\{([a-z]+)\}', segment)
    if match is None or not syllable.endswith(match[1]):
        return {'state': 'unsupported_annotation', **common}
    actual = syllable[:-len(match[1])] + match[2]
    actual_group = nasal_group(model_final(actual))
    if actual_group is None or actual_group == expected:
        return {'state': 'other_segmental_change', **common}
    pure = (actual == syllable + 'g' or syllable == actual + 'g')
    return {'state': 'nasal_substitution', 'actual_label': actual_group,
            'actual_pinyin': actual, 'pure_nasal_pair': pure,
            'label_source': 'explicit_suffix_substitution', **common}


def map_nominal(items, reference):
    """Require the complete nominal syllable sequence, including erhua spans."""
    chars = ''.join(c for c in reference if '\u3400' <= c <= '\u9fff')
    expected = lazy_pinyin(chars, style=Style.NORMAL)
    selected = [(i, r) for i, r in enumerate(items) if r['text'].strip() not in ('', 'pau', 'paus')]
    cursor = 0
    result = []
    for index, row in selected:
        syllable = re.sub(r'[0-4]$', '', row['text'].strip()).replace('v', 'ü')
        if cursor >= len(chars):
            return None
        span = 1
        if syllable.endswith('r') and cursor + 1 < len(chars) and chars[cursor + 1] == '儿':
            syllable = syllable[:-1]
            span = 2
        if syllable != expected[cursor]:
            return None
        result.append({'tier_index': index, 'position': cursor, 'char_span': span})
        cursor += span
    return result if cursor == len(chars) else None


def same_interval(first, second):
    return all(abs(first[k] - second[k]) < 1e-7 for k in ('start', 'end'))


def auxiliary_conflict(nominal, primary_error, tiers):
    """Do not mistake a blank primary tier for agreement across all tiers."""
    primary_segment = re.sub(r'TT?[0-4]\{[0-4]\}', '', primary_error).strip()
    for name, items in tiers.items():
        if name in ('NP', 'ER', 'EI', 'Misc'):
            continue
        for item in items:
            if not (item['start'] < nominal['end'] and item['end'] > nominal['start']):
                continue
            value = re.sub(r'TT?[0-4]\{[0-4]\}', '', item['text']).strip()
            if value and (name != 'IP' or not primary_segment or value != primary_segment):
                return True
    return False


def inventory():
    import parselmouth
    from parselmouth.praat import call
    output = BASE / 'annotations-v1.json'
    if output.exists():
        raise ValueError('Annotation inventory is frozen')
    archive = BASE / '10072-395757_Tsurutani.zip'
    source = json.loads((BASE / 'source.json').read_text())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != source['sha256']:
        raise ValueError('Source archive changed')
    rows = []
    with ZipFile(archive) as bundle, tempfile.TemporaryDirectory(prefix='pth-griffith-') as temporary:
        path = Path(temporary) / 'source.TextGrid'
        for name in bundle.namelist():
            if not name.startswith('File 1 Aus 1-22/') or not name.endswith('.TextGrid'):
                continue
            data = bundle.read(name)
            path.write_bytes(data)
            grid = parselmouth.read(str(path))
            tiers = {}
            for i in range(1, call(grid, 'Get number of tiers') + 1):
                label = call(grid, 'Get tier name', i)
                if label in tiers:
                    raise ValueError('Duplicate annotation tier')
                tiers[label] = [
                    {'start': call(grid, 'Get start time of interval', i, j),
                     'end': call(grid, 'Get end time of interval', i, j),
                     'text': call(grid, 'Get label of interval', i, j)}
                    for j in range(1, call(grid, 'Get number of intervals', i) + 1)]
            audio = name[:-9] + '.wav'
            rows.append({'member': name, 'speaker': name.split('/')[1], 'audio_member': audio,
                         'audio_exists': audio in bundle.namelist(),
                         'annotation_sha256': hashlib.sha256(data).hexdigest(), 'tiers': tiers})
    save_json(output, {'complete': True, 'archive_sha256': source['sha256'],
                       'parser': 'praat-parselmouth==' + parselmouth.__version__, 'rows': rows})
    print('inventory', len(rows), 'recordings', len({r['speaker'] for r in rows}), 'speakers')


def prepare(folder, selected_from=None):
    if (folder / 'input.json').exists():
        raise ValueError('Independent probe selection is frozen')
    inventory_data = json.loads((BASE / 'annotations-v1.json').read_text())
    stimuli = json.loads((BASE / 'stimuli.json').read_text())
    candidates = []
    excluded = []
    label_counts = Counter()
    for rec in inventory_data['rows']:
        numbers = re.findall(r'(?:^|_)(\d{2})(?:_|\.)', Path(rec['member']).name)
        if len(numbers) != 1 or numbers[0] not in stimuli or not rec['audio_exists']:
            excluded.append({'member': rec['member'], 'reason': 'unmatched_stimulus_or_audio'})
            continue
        reference = stimuli[numbers[0]]
        tiers = rec['tiers']
        mapping = map_nominal(tiers['NP'], reference)
        error_tiers = [k for k in ('ER', 'EI') if k in tiers]
        if mapping is None or len(error_tiers) != 1:
            excluded.append({'member': rec['member'], 'reason': 'nominal_sequence_or_error_tier_mismatch'})
            continue
        errors = tiers[error_tiers[0]]
        misc = tiers['Misc']
        if len(errors) != len(tiers['NP']) or len(misc) != len(tiers['NP']):
            excluded.append({'member': rec['member'], 'reason': 'tier_length_mismatch'})
            continue
        targets = []
        for item in mapping:
            i = item['tier_index']; nominal = tiers['NP'][i]
            if not same_interval(nominal, errors[i]) or not same_interval(nominal, misc[i]):
                excluded.append({'member': rec['member'], 'position': item['position'], 'reason': 'tier_time_mismatch'})
                continue
            label = annotation_label(nominal['text'], errors[i]['text'], misc[i]['text'])
            if label['state'] in ('normal_annotation', 'nasal_substitution') and auxiliary_conflict(nominal, errors[i]['text'], tiers):
                label = {'state': 'auxiliary_annotation_conflict'}
            label_counts[label['state']] += 1
            if label['state'] not in ('normal_annotation', 'nasal_substitution'):
                if label['state'] != 'not_supported_nasal':
                    excluded.append({'member': rec['member'], 'position': item['position'],
                                     'reason': label['state'], 'annotation': errors[i]['text']})
                continue
            targets.append({**label, 'position': item['position'], 'human_syllable': [nominal['start'], nominal['end']],
                            'nominal_pinyin': nominal['text'], 'annotation': errors[i]['text']})
        candidates.append({**{k: rec[k] for k in ('member', 'speaker', 'audio_member', 'annotation_sha256')},
                           'reference': reference, 'targets': targets})
    # All explicitly interpretable errors plus two deterministic normal-containing
    # recordings per speaker. No acoustic/API prediction participates in selection.
    selected = {r['member'] for r in candidates if any(t['state'] == 'nasal_substitution' for t in r['targets'])}
    pools = defaultdict(list)
    for rec in candidates:
        if any(t['state'] == 'normal_annotation' for t in rec['targets']):
            pools[rec['speaker']].append(rec)
    for pool in pools.values():
        ranked = sorted(pool, key=lambda r: hashlib.sha256((SEED + r['member']).encode()).hexdigest())
        selected.update(r['member'] for r in ranked[:2])
    if selected_from is not None:
        # A source-label repair retains the prior recording selection; it must
        # not replace uncertain targets with easier cases after API observations.
        selected = {r['member'] for r in json.loads(Path(selected_from).read_text())['records']}
    folder.mkdir(parents=True, exist_ok=True)
    audio_dir = folder / 'audio'; audio_dir.mkdir(exist_ok=True)
    records = []
    with ZipFile(BASE / '10072-395757_Tsurutani.zip') as bundle:
        for rec in candidates:
            if rec['member'] not in selected:
                continue
            uid = 'griffith-' + hashlib.sha256(rec['member'].encode()).hexdigest()[:16]
            source = audio_dir / (uid + '-source.wav'); audio = audio_dir / (uid + '.wav')
            source.write_bytes(bundle.read(rec['audio_member'])); source.chmod(0o600)
            if not audio.exists():
                subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(source), '-ac', '1',
                                '-ar', '16000', '-c:a', 'pcm_s16le', str(audio)], check=True)
                audio.chmod(0o600)
            with wave.open(str(audio), 'rb') as wav:
                duration = wav.getnframes() / wav.getframerate()
            if not .1 < duration < 60 or any(not 0 <= t['human_syllable'][0] < t['human_syllable'][1] <= duration + .01 for t in rec['targets']):
                raise ValueError('Human target timing outside source audio')
            records.append({**rec, 'uid': uid, 'speaker': 'griffith:' + rec['speaker'], 'split': 'external',
                            'core': 'read_sentence', 'audio': str(audio), 'duration': duration,
                            'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
    cases = [{'id': r['uid'], 'audio': r['audio'], 'reference': r['reference'], 'core': r['core'],
              'position': r['targets'][0]['position'], 'condition': 'external_sentence_carrier'} for r in records if r['targets']]
    save_json(folder / 'input.json', {'records': records, 'cases': cases, 'excluded': excluded,
              'inventory_labels': dict(label_counts), 'archive_sha256': inventory_data['archive_sha256'],
              'seed': SEED, 'selection_used_predictions': False, 'evaluation_only': True,
              'annotation_policy_version': 2, 'retained_recording_selection_from': selected_from,
              'limits': ['Published paper describes consensus error annotation, not per-target independent scores.',
                         'Archive File 1 contains 29 speakers, not all 33 described in the paper.',
                         'Undecoded annotations and nominal/reference conflicts are not treated as correct.',
                         'Explicit substitutions can involve other segmental changes; pure pairs are separate.']})
    print('selected', len(records), 'recordings', dict(Counter(t['state'] for r in records for t in r['targets'])),
          'inventory', dict(label_counts), 'excluded', len(excluded), flush=True)


async def freeze(folder):
    from ise_probe import IseProbe, public_result, target_at
    from prepare_nasal_feature_data import interval
    output = folder / 'dataset.json'
    if output.exists():
        raise ValueError('Independent dataset is frozen')
    manifest = json.loads((folder / 'input.json').read_text())
    ledger = Path('data/derived/ise-validation/requests.json'); before = ledger.read_bytes()
    probe = IseProbe(ledger.parent, allow_paid=False)
    rows = []; excluded = []
    for rec in manifest['records']:
        result = public_result(await probe.call(rec['audio'], rec['reference'], core=rec['core']))
        for target in rec['targets']:
            row = {**target, **{k: rec[k] for k in ('speaker', 'split', 'audio', 'reference', 'core')},
                   'id': rec['uid'] + '-pos' + str(target['position']), 'cohort': 'external_griffith',
                   'condition': 'sentence_error' if target['state'] == 'nasal_substitution' else 'consensus_control'}
            observation = target_at(result, rec['reference'], target['position'])
            bounds = interval(observation, rec['audio'])
            row['api_state'] = observation['state']
            if bounds is None:
                excluded.append({**row, 'reason': 'unusable_cached_interval'})
            else:
                rows.append({**row, 'bounds': bounds, 'audio_sha256': hashlib.sha256(Path(rec['audio']).read_bytes()).hexdigest()})
    if before != ledger.read_bytes():
        raise ValueError('Cache-only preparation changed the ledger')
    save_json(output, {'rows': rows, 'excluded': excluded, 'evaluation_only': True,
                       'selection_used_predictions': False, 'limits': manifest['limits']})
    print('usable', len(rows), 'excluded', len(excluded), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['inventory', 'prepare', 'freeze'])
    parser.add_argument('--directory', default='data/derived/nasal-acoustic-validation/griffith-external-v2')
    parser.add_argument('--selected-from', help='Retain a frozen recording selection when repairing source-label interpretation.')
    args = parser.parse_args()
    if args.mode == 'inventory': inventory()
    elif args.mode == 'prepare': prepare(Path(args.directory), args.selected_from)
    else: asyncio.run(freeze(Path(args.directory)))
