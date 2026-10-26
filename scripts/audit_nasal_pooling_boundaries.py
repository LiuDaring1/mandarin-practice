"""Post-hoc audit of the frames pooled from each target, without relabelling.

Whole-syllable overlap can conceal an inaccurate vowel-tail boundary. Published
human syllable times are used only for this diagnostic, never as runtime input.
"""
from collections import Counter
import json
from pathlib import Path
import wave

import numpy as np

from train_nasal_feature_probe import save_json


def tail_coverage(bounds, human, sample_count):
    # Fixed encoder geometry: 400-sample receptive field, 320-sample stride.
    count = (sample_count - 400) // 320 + 1
    times = (np.arange(count) * 320 + 200) / 16000
    begin, end = bounds['vowel']
    selected = times[(times >= (begin + end) / 2) & (times < end)]
    if not len(selected):
        return {'state': 'empty_pool', 'frames': 0}
    inside = (selected >= human[0]) & (selected < human[1])
    return {'state': 'measured', 'frames': len(selected), 'frames_in_human_syllable': int(inside.sum()),
            'outside_fraction': float(1 - inside.mean()), 'frame_centers': selected.tolist()}


def main():
    folder = Path('data/derived/nasal-acoustic-validation/griffith-external-v2')
    output = folder / 'pooling-boundary-audit.json'
    if output.exists():
        raise ValueError('Pooling diagnostic is frozen')
    dataset = json.loads((folder / 'dataset.json').read_text())
    evaluation = json.loads((folder / 'exact-evaluation.json').read_text())
    predictions = {r['id']: r for r in evaluation['comparison']['context-exact-margin-v5']['predictions']}
    rows = []
    for row in dataset['rows']:
        if row['id'] not in predictions:
            continue
        with wave.open(row['audio'], 'rb') as wav:
            if wav.getframerate() != 16000:
                raise ValueError('Unexpected audio rate')
            count = wav.getnframes()
        observation = predictions[row['id']]
        rows.append({'id': row['id'], 'human_syllable': row['human_syllable'], 'api_bounds': row['bounds'],
                     'false_reassurance': bool(observation['candidate_nasal_match'] and observation['actual'] != observation['expected']),
                     'known_error': observation['actual'] != observation['expected'],
                     **tail_coverage(row['bounds'], row['human_syllable'], count)})
    measured = [r for r in rows if r['state'] == 'measured']
    report = {'complete': True, 'post_hoc': True, 'rows': rows,
              'targets': len(rows), 'states': dict(Counter(r['state'] for r in rows)),
              'majority_of_tail_frames_outside_human_syllable': sum(r['outside_fraction'] > .5 for r in measured),
              'false_reassurance_audits': [r for r in rows if r['false_reassurance']],
              'limits': ['Human timing is not a perfect physical phoneme boundary.',
                         'This does not prove that pooling caused the diagnostic error.',
                         'No target is removed and no model threshold/label is changed.']}
    save_json(output, report)
    print(json.dumps({k: v for k, v in report.items() if k not in ('rows', 'false_reassurance_audits')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
