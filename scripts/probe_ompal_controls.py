"""Measure false-alarm candidates on whole, independently scored sentences."""
import argparse
import json
from pathlib import Path

from nasal_acoustics import AcousticModel, nasal_group
from probe_nasal_context import compare_target


def main(args):
    folder = Path('data/derived/nasal-acoustic-validation/ompal')
    manifest = json.loads(Path(args.input).read_text())
    model = AcousticModel('final')
    observations = {}
    references = {}
    for recording in manifest['recordings']:
        chars = [c for c in recording['reference'] if '\u3400' <= c <= '\u9fff']
        if len(chars) != len(recording['finals']):
            raise ValueError('Reference/final count mismatch')
        references[recording['audio']] = recording['reference']
        result = model.infer(recording['audio'], folder.parent / 'logits')
        greedy = [s['token'] for s in result['spans']]
        for target in recording['targets']:
            position = target['position']
            comparison = compare_target(result['logits'], model.vocab, recording['finals'], position)
            identity = (recording['audio'], position)
            observations[identity] = {'local': comparison,
                'local_greedy_group': nasal_group(greedy[position]) if len(greedy) == len(recording['finals']) else None,
                'cache_key': result['key'], 'greedy_finals': greedy}
        print(recording['uid'], 'targets', len(recording['targets']), flush=True)
    for row in manifest['cases']:
        if row['reference'] != references[row['audio']]:
            raise ValueError('Target references a different text for the recording')
        row.update(observations[row['audio'], row['position']])
    output = Path(args.output)
    output.write_text(json.dumps({**manifest, 'complete': True}, ensure_ascii=False, indent=2))
    output.chmod(0o600)
    print('COMPLETE', len(manifest['cases']), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='data/derived/nasal-acoustic-validation/ompal/controls-input.json')
    parser.add_argument('--output', default='data/derived/nasal-acoustic-validation/ompal/controls-with-local.json')
    main(parser.parse_args())
