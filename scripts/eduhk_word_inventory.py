"""Audit per-character web annotations without treating each row as a reading.

Research only: phonetic matching may use the published substitution to locate
an error. This is not an alignment algorithm for unlabelled learner recordings.
The old inventory, audio crops, and experiments are never rewritten.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

from lxml import html
from pypinyin import Style, lazy_pinyin

from collect_eduhk_nasal import parse_annotations
from prepare_eduhk_crops import ALIGNER_REVISION, edit_distance, spoken_list_start
from train_nasal_feature_probe import save_json

BASE = Path('data/derived/nasal-acoustic-validation')
SOURCE = BASE / 'eduhk'
OUTPUT = BASE / 'eduhk-word-recovery-v2'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def positional_rows(raw, speaker, source):
    """Retain the bold target before the line break, never the bold error note."""
    old = parse_annotations(raw, speaker, source)
    nodes = html.fromstring(raw).xpath('//span[contains(@id,"ResultElement")]')
    result = []
    for row, node in zip(old, nodes, strict=True):
        prefix = node.text or ''
        highlighted = []
        for child in node:
            if child.tag.lower() == 'br':
                break
            text = child.text_content()
            if child.tag.lower() == 'b':
                highlighted.extend(range(len(prefix), len(prefix) + len(text)))
            prefix += text + (child.tail or '')
        if prefix.strip() != row['word'] or prefix != prefix.strip():
            raise ValueError('Unexpected whitespace or markup in target positions')
        if row['nasal_errors'] and len(highlighted) != 1:
            raise ValueError('Explicit nasal error needs one unambiguous highlighted character')
        target = highlighted[0] if len(highlighted) == 1 else None
        errors = [{**error, 'position': target, 'character': row['word'][target],
                   'source_word_index': row['word_index']} for error in row['nasal_errors']]
        result.append({**row, 'highlighted_positions': highlighted, 'nasal_errors': errors})
    return result


def group_display_rows(rows):
    """Merge only complementary highlighted positions of the same written word."""
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row['speaker'], row['task'], row['word'])].append(row)
    result = []
    for (_, _, word), copies in grouped.items():
        positions = [p for row in copies for p in row['highlighted_positions']]
        mergeable = len(copies) == 1 or (
            all(row['highlighted_positions'] for row in copies)
            and len(positions) == len(set(positions)))
        errors = [error for row in copies for error in row['nasal_errors']]
        if len({e['position'] for e in errors}) != len(errors):
            mergeable = False
        result.append({'speaker': copies[0]['speaker'], 'task': copies[0]['task'],
                       'word': word, 'source_rows': copies, 'nasal_errors': errors,
                       'mergeable': mergeable})
    return result


def match_word(syllables, group, start_at=0):
    if not group['mergeable']:
        return None
    expected = lazy_pinyin(group['word'], style=Style.NORMAL)
    actual = expected.copy()
    for error in group['nasal_errors']:
        # The annotation fixes the intended reading as well as the observed one.
        expected[error['position']] = error['expected_plain']
        actual[error['position']] = error['actual_plain']
    candidates = []
    for start in range(start_at, len(syllables) - len(expected) + 1):
        sample = syllables[start:start + len(expected)]
        cost = min(sum(edit_distance(a, b) for a, b in zip(sample, variant))
                   for variant in (expected, actual))
        candidates.append((cost, start))
    candidates.sort()
    if not candidates or candidates[0][0] > (1 if len(expected) == 1 else 2):
        return None
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return None
    return {'start': candidates[0][1], 'length': len(expected), 'cost': candidates[0][0]}


def collision_free(matches):
    """Only a strictly better phonetic match may own an overlapping interval.

    Losing or tied claims stay unresolved, including different-length overlaps.
    A winner is not inferred from whether the target is annotated as erroneous.
    """
    accepted = set()
    for index, match in enumerate(matches):
        if match is None:
            continue
        left, right = match['start'], match['start'] + match['length']
        competitors = [other for j, other in enumerate(matches) if j != index and other is not None
                       and max(left, other['start']) < min(right, other['start'] + other['length'])]
        if all(match['cost'] < other['cost'] for other in competitors):
            accepted.add(index)
    return accepted


def current_partitions(dataset):
    """Available speaker assignments take precedence over old unavailable rows.

    Never move a held-out speaker into training because an earlier API failure
    retained its old split. Every such historical discrepancy is recorded.
    """
    splits, discrepancies = {}, []
    for row in dataset['rows']:
        if row['speaker'] in splits and splits[row['speaker']] != row['split']:
            raise ValueError('Inconsistent available speaker partition')
        splits[row['speaker']] = row['split']
    for row in dataset['excluded']:
        previous = splits.setdefault(row['speaker'], row['split'])
        if previous != row['split']:
            if previous in ('train', 'dev') or row['split'] not in ('train', 'dev'):
                raise ValueError('Cannot resolve historical speaker partition safely')
            discrepancies.append({'id': row['id'], 'old_split': row['split'], 'current_split': previous})
    return splits, discrepancies


def prepare():
    if OUTPUT.exists():
        raise ValueError('Recovery inventory is frozen; use a new experiment for revisions')
    pages = sorted(SOURCE.glob('speaker-*-vowels.html'))
    sources = pages + [SOURCE / 'annotations.json', SOURCE / 'crops.json', SOURCE / 'final-report.json',
                       BASE / 'context-training-v4/dataset.json', Path(__file__),
                       Path('scripts/collect_eduhk_nasal.py'), Path('scripts/prepare_eduhk_crops.py')]
    sources += sorted(SOURCE.glob('*.asr-v2.json')) + sorted((SOURCE / 'alignments').glob('*.json'))
    plan = {'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
            'sources': {str(p): digest(p) for p in sources},
            'uses_model_assessment_for_selection': False, 'uses_published_actual_pronunciation_for_location': True,
            'new_blind_validation': False, 'unmarked_rows_are_normal_labels': False,
            'alignment_reviewed_by_human': False,
            'rules': ['Complementary bold character rows share one word recording.',
                      'Repeated identical target rows and equal-cost audio occurrences remain ambiguous.',
                      'An overlapping word claim only survives a strictly lower edit cost.',
                      'Keep every original error in the denominator and preserve speaker partitions.']}
    OUTPUT.mkdir()
    save_json(OUTPUT / 'plan.json', plan)
    parsed = []
    for page in pages:
        speaker = int(re.search(r'speaker-(\d+)-', page.name).group(1))
        url = f'https://lml-elearning.eduhk.hk/ViewTaskOneAndTwo_g.aspx?id={speaker}'
        parsed.extend(positional_rows(page.read_bytes(), speaker, url))
    original = json.loads((SOURCE / 'annotations.json').read_text())['rows']
    original_ids = {(r['speaker'], r['task'], r['word_index']): r for r in original}
    if len(original_ids) != len(parsed):
        raise ValueError('Source row inventory changed')
    for row in parsed:
        old = original_ids[(row['speaker'], row['task'], row['word_index'])]
        if row['word'] != old['word'] or [
            {k: e[k] for k in old['nasal_errors'][i]} for i, e in enumerate(row['nasal_errors'])
        ] != old['nasal_errors']:
            raise ValueError('Source text or original labels changed')
    previous = json.loads((SOURCE / 'final-report.json').read_text())['rows']
    old_errors = {(r['speaker'], r['task'], r['word_index'], r['target_position']): r
                  for r in previous if r['annotated_substitution']}
    split_data = json.loads((BASE / 'context-training-v4/dataset.json').read_text())
    splits, split_discrepancies = current_partitions(split_data)
    groups = group_display_rows(parsed)
    recordings = defaultdict(list)
    for group in groups:
        recordings[(group['speaker'], group['task'])].append(group)
    recovered, unresolved, all_targets = [], [], []
    (OUTPUT / 'crops').mkdir()
    for (speaker, task), words in recordings.items():
        if not any(g['nasal_errors'] for g in words):
            continue
        source = SOURCE / 'audio' / f'T{speaker}_T{task}.mp3'
        asr = SOURCE / (source.name + '.asr-v2.json')
        if not source.exists() or not asr.exists():
            raise ValueError('Missing previously collected error recording')
        transcript = json.loads(asr.read_text())
        if transcript['audio_sha256'] != digest(source):
            raise ValueError('Audio differs from the free transcript')
        text = ''.join(ch for ch in transcript['text'] if '\u3400' <= ch <= '\u9fff')
        key = hashlib.sha256(source.read_bytes() + text.encode() + ALIGNER_REVISION.encode() + b'free-asr-v2').hexdigest()
        aligned = json.loads((SOURCE / 'alignments' / (key + '.json')).read_text())['items']
        if ''.join(t['text'] for t in aligned) != text:
            raise ValueError('Free transcript and alignment differ')
        matches = [match_word(lazy_pinyin(text, style=Style.NORMAL), g, spoken_list_start(text)) for g in words]
        accepted = collision_free(matches)
        duration = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                         '-of', 'default=nw=1:nk=1', str(source)], text=True).strip())
        for index, group in enumerate(words):
            for error in group['nasal_errors']:
                identity = (speaker, task, error['source_word_index'], error['position'])
                uid = f'eduhk-s{speaker}-t{task}-w{error["source_word_index"]}-p{error["position"]}'
                target = {'id': uid, 'speaker': f'eduhk:{speaker}', 'split': splits.get(f'eduhk:{speaker}', 'validation'),
                          'task': task, 'reference': group['word'], 'position': error['position'], 'annotation': error,
                          'previously_scored': identity in old_errors, 'source_audio': str(source),
                          'source_sha256': digest(source), 'source_row_indices': [r['word_index'] for r in group['source_rows']],
                          'alignment_reviewed_by_human': False}
                if identity in old_errors:
                    old = old_errors[identity]
                    if old['annotated_substitution']['actual_plain'] != error['actual_plain']:
                        raise ValueError('Previous scored target label differs')
                all_targets.append(target)
                match = matches[index]
                reason = ('unmergeable_display_rows' if not group['mergeable'] else
                          'ambiguous_or_distant_transcript_match' if match is None else
                          'overlapping_claim_not_strictly_best' if index not in accepted else None)
                if reason:
                    unresolved.append({**target, 'reason': reason})
                    continue
                times = aligned[match['start']:match['start'] + match['length']]
                if (any(t['end'] - t['start'] < .08 for t in times)
                    or times[-1]['end'] - times[0]['start'] > max(4, len(times) * 1.5)):
                    unresolved.append({**target, 'reason': 'suspect_alignment'})
                    continue
                start, end = max(0., times[0]['start'] - .10), min(duration, times[-1]['end'] + .10)
                if not 0 <= start < end <= duration:
                    raise ValueError('Out-of-range recovery crop')
                target_time = times[error['position']]
                record = {**target, 'crop_start': start, 'crop_end': end, 'alignment': times,
                          'transcript_match': match, 'matched_transcript': ''.join(t['text'] for t in times),
                          'bounds': {'syllable': [target_time['start'] - start, target_time['end'] - start]},
                          'alignment_key': key}
                if not target['previously_scored']:
                    audio = OUTPUT / 'crops' / (uid + '.wav')
                    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(source), '-ss', str(start),
                                    '-t', str(end-start), '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(audio)], check=True)
                    audio.chmod(0o600)
                    record.update(audio=str(audio), audio_sha256=digest(audio))
                recovered.append(record)
    if len(all_targets) != 92 or len({r['id'] for r in all_targets}) != 92:
        raise ValueError('Original explicit error denominator changed')
    if sum(r['previously_scored'] for r in all_targets) != len(old_errors):
        raise ValueError('Old scored error position could not be found in highlighted annotation')
    report = {'complete': True, 'plan_sha256': digest(OUTPUT/'plan.json'), 'targets': all_targets,
              'historical_unavailable_split_discrepancies': split_discrepancies,
              'located': recovered, 'unresolved': unresolved,
              'summary': {'original_errors': len(all_targets), 'previously_scored': len(old_errors),
                          'located_now': len(recovered), 'newly_located': sum(not r['previously_scored'] for r in recovered),
                          'previously_scored_now_unresolved': sum(r['previously_scored'] for r in unresolved),
                          'remaining_previously_unscored': sum(not r['previously_scored'] for r in unresolved),
                          'unresolved_reasons': dict(Counter(r['reason'] for r in unresolved))},
              'limits': ['Source bold position is audited; audio boundaries are still automatic, not human truth.',
                         'Recovered samples share existing speakers and are not independent blind validation.',
                         'No classification outcome used to recover or discard a target.']}
    save_json(OUTPUT/'inventory.json', report)
    save_json(OUTPUT/'recovered-input.json', {'cases': [{**r, 'condition': 'annotated_error',
              'core': 'read_syllable' if len(r['reference']) == 1 else 'read_word'}
              for r in recovered if not r['previously_scored']], 'plan_sha256': digest(OUTPUT/'plan.json')})
    print(json.dumps(report['summary'], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    prepare()
