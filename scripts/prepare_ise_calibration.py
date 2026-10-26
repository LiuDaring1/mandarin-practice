"""Prepare bounded, cached ISE comparison cases from existing research results."""
import json
from pathlib import Path


def main():
    from opencc import OpenCC
    converter = OpenCC('tw2s')
    base = Path('data/derived/nasal-acoustic-validation')
    cases = []
    for source, condition in [('eduhk-native', 'standard_reference'), ('eduhk', 'annotated_error')]:
        folder = base / source
        report = json.loads((folder / 'final-report.json').read_text())
        if report.get('complete') is not True:
            raise ValueError('Incomplete local comparison')
        crops = json.loads((folder / 'crops.json').read_text())['rows']
        lookup = {(r['speaker'], r['task'], r['word_index']): r for r in crops}
        for row in report['rows']:
            if condition == 'annotated_error' and not row['annotated_substitution']:
                continue
            crop = lookup[row['speaker'], row['task'], row['word_index']]
            reference = converter.convert(row['word'])
            if len(reference) != len(row['word']):
                raise ValueError('Conversion changed character positions')
            cases.append({'id': f"{source}-s{row['speaker']}-t{row['task']}-w{row['word_index']}-p{row['target_position']}",
                          'condition': condition, 'audio': crop['audio'], 'reference': reference,
                          'position': row['target_position'], 'core': 'read_syllable' if len(reference) == 1 else 'read_word',
                          'annotation': row['annotated_substitution'], 'local': row['comparison'],
                          'local_greedy_group': row['greedy_target_group'], 'alignment_reviewed_by_human': False})
    output = base / 'ise-word-calibration-input.json'
    output.write_text(json.dumps({'cases': cases}, ensure_ascii=False, indent=2))
    output.chmod(0o600)
    print('target_cases', len(cases), 'unique_audio_references', len({(r['audio'], r['reference']) for r in cases}))


if __name__ == '__main__':
    main()
