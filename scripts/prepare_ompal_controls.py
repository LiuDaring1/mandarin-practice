"""Select model-blind sentence controls with published vowel-correct labels.

Source: https://github.com/phantomhsieh/OMPAL-corpus (CC BY 4.0).
Non-native targets require at least three unanimous raw vowel scores of 1.
Native reference scores are reported separately, not called independent votes.
"""
from collections import Counter
import json
import hashlib
from pathlib import Path
import random
import subprocess
import urllib.request

from pypinyin import lazy_pinyin, Style
from probe_eduhk_nasal import model_final


def unanimous_correct(values):
    if not isinstance(values, list) or len(values) < 3:
        return False
    try:
        return all(float(v) == 1 for v in values)
    except (ValueError, TypeError):
        return False


def main():
    from opencc import OpenCC
    converter = OpenCC('tw2s')
    folder = Path('data/derived/nasal-acoustic-validation/ompal')
    native = json.loads((folder / 'native_scores.json').read_text())
    learner = json.loads((folder / 'non-native_scores-detail.json').read_text())
    aggregate = json.loads((folder / 'non-native_scores.json').read_text())
    revision = json.loads((folder / 'source-revision.json').read_text())['commit']
    tree = json.loads((folder / 'tree.json').read_text())['tree']
    paths = {Path(r['path']).stem: r['path'] for r in tree if r['path'].endswith('.wav')}
    candidates = []
    missing_audio = []
    for condition, corpus in [('native_reference_score', native), ('unanimous_learner_vowel_correct', learner)]:
        for uid, record in corpus.items():
            if uid not in paths:
                missing_audio.append(uid)
                continue
            chars = [ch for ch in record['text'] if '\u3400' <= ch <= '\u9fff']
            labels = record['words']
            if any(len(w['text']) != 1 or len(w['text'][0]) != 1 for w in labels):
                continue
            if [w['text'][0] for w in labels] != chars:
                continue
            if condition.startswith('unanimous'):
                # Some detailed-score IDs have no corresponding WAV in the
                # release. Never infer a renamed identity or silently join by
                # text: many speakers read the same sentences.
                summary = aggregate.get(uid)
                if summary is None or summary['text'] != record['text'] or [w['text'] for w in summary['words']] != [w['text'] for w in labels]:
                    raise ValueError('Detailed/aggregate annotation identity mismatch')
            reference = converter.convert(''.join(chars))
            if len(reference) != len(chars):
                continue
            syllables = lazy_pinyin(reference, style=Style.NORMAL)
            finals = [model_final(p) for p in syllables]
            targets = []
            for i, final in enumerate(finals):
                if not final.endswith(('n', 'ng')):
                    continue
                other = final[:-1] if final.endswith('ng') else final + 'g'
                # The current pair comparison excludes finals without a real partner.
                if other not in {'an','ang','en','eng','in','ing','ian','iang','uan','uang','uen','ueng'}:
                    continue
                score = labels[i]['phoneme_vowel']
                correct = unanimous_correct(score) if condition.startswith('unanimous') else score == 1
                if correct and condition.startswith('unanimous') and summary['words'][i]['phoneme_vowel'] != 1:
                    raise ValueError('Unanimous label contradicts aggregate label')
                if correct:
                    targets.append({'position': i, 'final': final, 'published_vowel_scores': score})
            if targets:
                candidates.append({'uid': uid, 'speaker': uid[:6], 'condition': condition,
                                   'reference': reference, 'finals': finals, 'targets': targets,
                                   'source_path': paths[uid]})
    rng = random.Random(20261027)
    native_speakers = sorted({r['speaker'] for r in candidates if r['condition'].startswith('native')})
    learner_speakers = sorted({r['speaker'] for r in candidates if r['condition'].startswith('unanimous')})
    rng.shuffle(learner_speakers)
    selected = []
    for speaker in native_speakers + learner_speakers[:12]:
        pool = [r for r in candidates if r['speaker'] == speaker]
        rng.shuffle(pool)
        selected.extend(pool[:2 if speaker in native_speakers else 1])
    (folder / 'audio').mkdir(exist_ok=True)
    cases = []
    for item in selected:
        source = folder / 'audio' / (item['uid'] + '-source.wav')
        url = f"https://raw.githubusercontent.com/phantomhsieh/OMPAL-corpus/{revision}/{item['source_path']}"
        if not source.exists():
            source.write_bytes(urllib.request.urlopen(url, timeout=30).read())
        audio = folder / 'audio' / (item['uid'] + '.wav')
        if not audio.exists():
            subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(source),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(audio)],check=True)
        item['audio'] = str(audio)
        item['source_url'] = url
        item['source_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
        item['audio_sha256'] = hashlib.sha256(audio.read_bytes()).hexdigest()
        for target in item['targets']:
            cases.append({'id': f"ompal-{item['uid']}-p{target['position']}",
                          'condition': item['condition'], 'reference': item['reference'],
                          'position': target['position'], 'audio': str(audio), 'core': 'read_sentence',
                          'annotation': {'vowel_correct': True, 'published_scores': target['published_vowel_scores']},
                          'local': None, 'local_greedy_group': None, 'whole_sentence_audio': True})
    manifest = {'source_revision': revision, 'selection_seed': 20261027,
                'selection_used_model_outputs': False, 'missing_audio_ids_excluded': missing_audio,
                'recordings': selected, 'cases': cases}
    output = folder / 'controls-input.json'
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    output.chmod(0o600)
    print('recordings', len(selected), 'targets', len(cases), 'conditions', dict(Counter(r['condition'] for r in cases)), flush=True)


if __name__ == '__main__':
    main()
