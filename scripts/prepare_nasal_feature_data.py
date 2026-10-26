"""Freeze speaker partitions before fitting a nasal acoustic classifier.

All vendor calls are cache-only. Labels come from published human annotations,
not ISE scores or model predictions. Untagged EdUHK positions are never positives.
"""
import asyncio
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import wave

from ise_probe import IseProbe, public_result, target_at
from nasal_acoustics import nasal_group
from prepare_ompal_controls import unanimous_correct
from suntone_probe import private_json


SEED = 'nasal-feature-speakers-20261027-v1'


def speaker_split(speaker):
    bucket = int(hashlib.sha256((SEED + ':' + speaker).encode()).hexdigest()[:8], 16) % 100
    return 'train' if bucket < 60 else 'dev' if bucket < 80 else 'test'


def label(final):
    return nasal_group(final) or 'other'


def interval(observation, audio):
    if observation['state'] not in ('flagged', 'not_flagged') or len(observation['finals']) != 1:
        return None
    node = observation['finals'][0]
    try:
        begin, end = [int(node[k])/100 for k in ('syll_beg_pos','syll_end_pos')]
        vowel_begin, vowel_end = [int(node[k])/100 for k in ('beg_pos','end_pos')]
    except (KeyError, ValueError, TypeError):
        return None
    with wave.open(str(audio), 'rb') as wav:
        duration = wav.getnframes()/wav.getframerate()
    if not 0 <= begin <= vowel_begin < vowel_end <= end <= duration + .01 or end - begin < .08:
        return None
    return {'syllable':[begin,end], 'vowel':[vowel_begin,vowel_end]}


async def main(args):
    base = Path('data/derived/nasal-acoustic-validation')
    folder = Path(args.directory)
    output = folder/'dataset.json'
    if output.exists():
        raise ValueError('Frozen dataset exists; inspect it rather than silently changing the split')
    probe = IseProbe(Path('data/derived/ise-validation'), allow_paid=False)
    before = Path('data/derived/ise-validation/requests.json').read_bytes()
    rows, excluded = [], []

    def append(row, observation):
        bounds = interval(observation, row['audio'])
        if bounds is None:
            excluded.append({k:row[k] for k in ('id','speaker','split','condition','actual_label')}
                            | {'reason':'unusable_cached_interval'})
            return
        rows.append({**row, 'bounds':bounds, 'audio_sha256':hashlib.sha256(Path(row['audio']).read_bytes()).hexdigest()})

    ompal = base/'ompal'
    native = json.loads((ompal/'native_scores.json').read_text())
    learner = json.loads((ompal/'non-native_scores-detail.json').read_text())
    aggregate = json.loads((ompal/'non-native_scores.json').read_text())
    recordings = json.loads((ompal/'controls-input.json').read_text())['recordings']
    if args.extra_recordings:
        recordings += json.loads(Path(args.extra_recordings).read_text())['recordings']
    for rec in recordings:
        uid = rec['uid']; is_native = uid in native
        record = native[uid] if is_native else learner[uid]
        if not is_native and record['text'] != aggregate[uid]['text']:
            raise ValueError('Annotation identity mismatch')
        if len(record['words']) != len(rec['finals']):
            raise ValueError('Annotation/final position mismatch')
        result = public_result(await probe.call(rec['audio'],rec['reference'],core='read_sentence'))
        speaker = 'ompal:' + rec['speaker']
        for pos, word in enumerate(record['words']):
            correct = word['phoneme_vowel'] == 1 if is_native else unanimous_correct(word['phoneme_vowel'])
            if not correct:
                continue
            if not is_native and aggregate[uid]['words'][pos]['phoneme_vowel'] != 1:
                raise ValueError('Conflicting teacher labels')
            expected = label(rec['finals'][pos])
            append({'id':f'ompal-{uid}-pos{pos}', 'speaker':speaker, 'split':speaker_split(speaker),
                    'condition':'native_reference' if is_native else 'teacher_correct',
                    'audio':rec['audio'], 'reference':rec['reference'], 'position':pos,
                    'expected_final':rec['finals'][pos], 'expected_label':expected,
                    'actual_label':expected, 'label_source':'native_score' if is_native else 'unanimous_vowel_scores'},
                   target_at(result, rec['reference'], pos))
    for source, name in [('ise-word-calibration-input.json','word'), ('eduhk-passages/probe-with-local.json','passage')]:
        cases = json.loads((base/source).read_text())['cases']
        for case in cases:
            if case['condition'] == 'standard_reference':
                continue  # weak reference-file labels are not teacher-certified training targets
            speaker = 'eduhk:' + case['id'].split('-s')[1].split('-')[0]
            actual = case['annotation']['actual_group']
            result = public_result(await probe.call(case['audio'],case['reference'],core=case['core']))
            append({'id':case['id'], 'speaker':speaker,
                    'split':'transfer' if name == 'passage' else speaker_split(speaker),
                    'condition':'sentence_error' if name == 'passage' else 'word_error',
                    'audio':case['audio'], 'reference':case['reference'], 'position':case['position'],
                    'expected_final':case['local']['final'], 'expected_label':label(case['local']['final']),
                    'actual_label':actual, 'label_source':'explicit_nasal_substitution'},
                   target_at(result,case['reference'],case['position']))
    splits = {}
    for row in rows:
        if row['speaker'] in splits and splits[row['speaker']] != row['split']:
            raise ValueError('Speaker leakage between splits')
        splits[row['speaker']] = row['split']
    after = Path('data/derived/ise-validation/requests.json').read_bytes()
    assert before == after, 'Cache-only construction changed the request ledger'
    private_json(output, {'version':1, 'seed':SEED, 'split_before_feature_extraction':True,
                         'label_inference_inputs':False, 'rows':rows, 'excluded':excluded,
                         'limits':['Automatic source/cached API timing needs boundary audit.',
                                   'These public recordings were used in earlier methods research; not untouched final validation.',
                                   'Transfer speakers do not appear in this classifier training split.']})
    print('ROWS',len(rows),'EXCLUDED',len(excluded),flush=True)
    for split in ['train','dev','test','transfer']:
        selected = [r for r in rows if r['split']==split]
        print(split,'speakers',len({r['speaker'] for r in selected}),'labels',dict(Counter(r['actual_label'] for r in selected)),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',default='data/derived/nasal-acoustic-validation/feature-classifier-v1')
    parser.add_argument('--extra-recordings')
    asyncio.run(main(parser.parse_args()))
