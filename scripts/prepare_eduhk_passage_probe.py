"""Select continuous readings without changing/cropping the nasal targets.

The first eight available speakers with passage-1 n/ng annotations not present
in the 51-target word-error comparison are used. This is new sentence context,
not a fully untouched speaker holdout (earlier unmarked-word exploration may
include these speakers). Labels choose the sample; model outputs never do.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request
import wave

from pypinyin import lazy_pinyin, Style

from probe_eduhk_nasal import model_final


def chinese_reference(text):
    """Remove editorial ASCII notes such as '(miss)'/'ok', retaining position.

    This corpus task is Chinese only. Preserve its Chinese characters and
    punctuation; notes remain available in the source text/HTML for audit.
    """
    return ''.join(c for c in text if '\u3400' <= c <= '\u9fff' or c in '，。！？：；、“”‘’—…')


def main():
    from opencc import OpenCC
    converter = OpenCC('tw2s')
    base = Path('data/derived/nasal-acoustic-validation')
    folder = base / 'eduhk-passages'
    annotations = json.loads((folder / 'annotations.json').read_text())
    if not annotations.get('complete'):
        raise ValueError('Incomplete annotation collection')
    word_cases = json.loads((base / 'ise-word-calibration-input.json').read_text())['cases']
    used = {int(r['id'].split('-s')[1].split('-')[0]) for r in word_cases if r['condition'] == 'annotated_error'}
    selected = [r for r in annotations['rows'] if r['passage'] == 1 and r['speaker'] not in used and r['nasal_errors']][:8]
    (folder / 'audio').mkdir(exist_ok=True)
    recordings, cases, excluded = [], [], []
    for row in selected:
        uid = f"eduhk-s{row['speaker']}-p{row['passage']}"
        source = folder / 'audio' / (uid + '.mp3')
        if not source.exists():
            source.write_bytes(urllib.request.urlopen(row['audio_url'], timeout=30).read())
        audio = folder / 'audio' / (uid + '.wav')
        if not audio.exists():
            subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(source),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(audio)],check=True)
        with wave.open(str(audio), 'rb') as wav:
            duration = wav.getnframes() / wav.getframerate()
        if not 0 < duration < 40:
            excluded.append({'uid':uid, 'reason':'exceeds_existing_probe_duration',
                             'duration':duration, 'error_targets':len(row['nasal_errors'])})
            continue
        reference = converter.convert(chinese_reference(row['text']))
        characters = ''.join(c for c in reference if '\u3400' <= c <= '\u9fff')
        if len(characters) != len(row['characters']) or len(characters) > 100:
            raise ValueError('Reference position/length mismatch')
        pinyin = lazy_pinyin(characters, style=Style.NORMAL)
        finals = [model_final(p) for p in pinyin]
        targets = []
        for label in row['nasal_errors']:
            position = label['position']
            if pinyin[position] != label['expected_plain']:
                raise ValueError('Context reading differs from annotation; must resolve before scoring')
            targets.append({'position':position, 'final':finals[position]})
            cases.append({'id':f'{uid}-pos{position}', 'condition':'annotated_sentence_error',
                          'audio':str(audio), 'reference':reference, 'position':position,
                          'core':'read_sentence', 'annotation':label, 'local':None,
                          'local_greedy_group':None, 'whole_sentence_audio':True})
        recordings.append({'uid':uid, 'speaker':row['speaker'], 'audio':str(audio),
                           'reference':reference, 'finals':finals, 'targets':targets,
                           'source_url':row['audio_url'], 'duration':duration,
                           'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                           'audio_sha256':hashlib.sha256(audio.read_bytes()).hexdigest()})
        print(uid, 'seconds', round(duration,2), 'targets', len(targets), flush=True)
    output = folder / 'probe-input.json'
    output.write_text(json.dumps({'selection_used_model_outputs':False,
        'selection':'first eight passage-1 error speakers outside the 51-target word-error comparison',
        'speaker_holdout_claim':False, 'selected_speakers':[r['speaker'] for r in selected],
        'excluded':excluded, 'recordings':recordings, 'cases':cases}, ensure_ascii=False, indent=2))
    output.chmod(0o600)


if __name__ == '__main__':
    main()
