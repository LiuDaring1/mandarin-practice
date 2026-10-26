"""Inventory unmarked TRAINING speech as weak-label candidates, never gold.

An unmarked character is not proof of correct pronunciation. This file does not
assign actual labels, change any training dataset, call an API or fit a model.
The inventory makes a future explicitly weak-supervision experiment reviewable.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from lxml import html
from pypinyin import Style, lazy_pinyin

from nasal_feature_probe import assert_speaker_partition
from probe_eduhk_nasal import model_final
from train_nasal_feature_probe import save_json

BASE = Path('data/derived/nasal-acoustic-validation')
FOLDER = BASE/'eduhk-unmarked-inventory-v1'
FINALS = ('an', 'ang', 'en', 'eng', 'ian', 'iang', 'in', 'ing')
SEED = 'eduhk-unmarked-inventory-20261027-v1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def marked_positions(node):
    """Count source character positions, excluding annotation text of any color."""
    chars = []; marked = set()
    def append(value):
        chars.extend(c for c in (value or '') if '\u3400'<=c<='\u9fff')
    def visit(element):
        if element.tag=='font':
            if element.text_content().strip():
                if not chars:
                    raise ValueError('Annotation without a preceding target')
                marked.add(len(chars)-1)
            return
        append(element.text)
        for child in element:
            visit(child)
            append(child.tail)
    visit(node)
    return ''.join(chars), marked


def select_candidates(rows, per_final_per_speaker=2):
    if per_final_per_speaker<1 or any(r['split']!='train' for r in rows):
        raise ValueError('Unmarked inventory must contain training rows only')
    if any('actual_label' in r for r in rows):
        raise ValueError('Unmarked speech cannot acquire a verified actual label')
    if len({r['id'] for r in rows})!=len(rows):
        raise ValueError('Duplicate inventory identity')
    groups = defaultdict(list)
    for row in rows:
        if row['expected_final'] not in FINALS:
            raise ValueError('Unsupported final in weak inventory')
        groups[(row['speaker'], row['expected_final'])].append(row)
    selected = []
    for key in sorted(groups):
        ordered = sorted(groups[key], key=lambda r: hashlib.sha256((SEED+r['id']).encode()).hexdigest())
        selected.extend(ordered[:per_final_per_speaker])
    return selected


def main():
    if FOLDER.exists():
        raise ValueError('Unmarked inventory already frozen')
    dataset_path = BASE/'fusion-vad-v2/existing-dataset.json'
    dataset = json.loads(dataset_path.read_text())
    all_rows = dataset['rows']+dataset['excluded']; assert_speaker_partition(all_rows)
    partitions = {r['speaker']: r['split'] for r in all_rows}
    input_path = BASE/'context-training-v4/input.json'
    records = [r for r in json.loads(input_path.read_text())['records'] if partitions.get(r['speaker'])=='train']
    annotation_path = BASE/'eduhk-passages/annotations.json'
    annotations = json.loads(annotation_path.read_text())
    if annotations.get('complete') is not True:
        raise ValueError('Incomplete annotation source')
    source_rows = {f"eduhk-s{r['speaker']}-p{r['passage']}": r for r in annotations['rows']}
    pages = {r['speaker']: BASE/'eduhk-passages'/f"speaker-{r['speaker'].split(':')[1]}-vowels.html" for r in records}
    files = [Path(__file__), Path('scripts/probe_eduhk_nasal.py'), dataset_path, input_path, annotation_path, *pages.values()]
    hashes = {str(path): sha(path) for path in files}
    candidates = []; exclusions = Counter(); recordings = []; cache = {}
    for rec in records:
        speaker = rec['speaker']; source = source_rows[rec['uid']]
        if speaker not in cache:
            nodes = html.fromstring(pages[speaker].read_bytes()).xpath('//span[contains(@id,"lblDisplayPara")]')
            if len(nodes)!=2:
                raise ValueError('Unexpected passage layout')
            cache[speaker] = [marked_positions(n) for n in nodes]
        original, marks = cache[speaker][source['passage']-1]
        reference_chars = ''.join(c for c in rec['reference'] if '\u3400'<=c<='\u9fff')
        if original!=source['characters'] or len(original)!=len(reference_chars):
            raise ValueError('Source/reference character positions changed')
        if any(error['position'] not in marks for error in source['nasal_errors']):
            raise ValueError('A known explicit nasal error was not marked')
        source_phones = lazy_pinyin(original, style=Style.NORMAL)
        phones = lazy_pinyin(reference_chars, style=Style.NORMAL)
        excluded_positions = {p+delta for p in marks for delta in (-1, 0, 1)}
        audio_digest = sha(rec['audio'])
        hashes[rec['audio']] = audio_digest
        recordings.append({'uid': rec['uid'], 'speaker': speaker, 'split': 'train',
                           'audio': rec['audio'], 'audio_sha256': audio_digest,
                           'marked_positions': sorted(marks), 'source': source['source']})
        for position, phone in enumerate(phones):
            final = model_final(phone)
            if final not in FINALS:
                continue
            if position in excluded_positions:
                exclusions['marked_or_adjacent'] += 1; continue
            if source_phones[position]!=phone:
                exclusions['reference_reading_difference'] += 1; continue
            candidates.append({'id': rec['uid']+'-unmarked-pos'+str(position), 'speaker': speaker, 'split': 'train',
                'audio': rec['audio'], 'audio_sha256': audio_digest, 'reference': rec['reference'],
                'core': rec['core'], 'position': position, 'expected_final': final,
                'expected_label': 'back' if final.endswith('ng') else 'front',
                'annotation_status': 'no_visible_vowel_annotation', 'label_status': 'unverified',
                'eligible_for_gold_evaluation': False, 'annotation_page_sha256': hashes[str(pages[speaker])]})
    selected = select_candidates(candidates)
    # Snapshot checks include the audio and full annotation pages, not model outputs.
    if any(sha(path)!=digest for path, digest in hashes.items()):
        raise ValueError('Inventory input changed during preparation')
    FOLDER.mkdir()
    save_json(FOLDER/'plan.json', {'frozen_at_utc': datetime.now(timezone.utc).isoformat(), 'sources': hashes,
        'split': 'train only, authoritative existing speaker map', 'reference_finals': FINALS,
        'selection': 'two per expected final per speaker by fixed SHA256 ordering', 'seed': SEED,
        'annotation_exclusion': 'any visible annotation and adjacent characters',
        'actual_labels_assigned': False, 'model_outputs_used': False, 'api_calls': 0,
        'purpose': 'Weak-supervision feasibility inventory, not new verified normal controls.'})
    report = {'complete': True, 'plan_sha256': sha(FOLDER/'plan.json'), 'recordings': recordings,
              'candidate_count': len(candidates), 'exclusions': dict(exclusions), 'selected': selected,
              'selected_by_final': dict(Counter(r['expected_final'] for r in selected)),
              'selected_speakers': len({r['speaker'] for r in selected}),
              'limitations': ['Unmarked syllables are not verified correct actual pronunciations.',
                  'No acoustic scores, API intervals or gold labels collected.',
                  'Only recordings already containing explicit nasal errors and assigned to train are inventoried.',
                  'No development or evaluation speakers are eligible.']}
    save_json(FOLDER/'inventory.json', report)
    print('INVENTORY', len(recordings), 'recordings', len(candidates), 'candidates', len(selected), 'selected',
          report['selected_speakers'], 'speakers', json.dumps(report['selected_by_final']), flush=True)


if __name__=='__main__':
    main()
