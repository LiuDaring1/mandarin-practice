"""Fixed public environmental recordings for prospective abstention checks.

No speech model selects examples. ESC-50 audio stays private (CC BY-NC 3.0).
These recordings are not user microphone data or proof of speech-in-noise safety.
"""
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import urllib.request

from train_nasal_feature_probe import save_json

REVISION = '33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6'
FOLDER = Path('data/derived/nasal-acoustic-validation/background-validation-v1')
CATEGORIES = ('rain', 'sea_waves', 'crackling_fire', 'keyboard_typing',
              'washing_machine', 'vacuum_cleaner', 'engine', 'clock_tick')
SEED = 'nasal-nonspeech-prospective-20261027-v1'


def select_recordings(rows):
    selected = []
    for category in CATEGORIES:
        pool = sorted((row for row in rows if row['category'] == category),
                      key=lambda row: hashlib.sha256((SEED+row['filename']).encode()).hexdigest())
        sources = set()
        for row in pool:
            if row['src_file'] in sources:
                continue
            sources.add(row['src_file'])
            selected.append(row)
            if len(sources) == 3:
                break
        if len(sources) != 3:
            raise ValueError('Insufficient independent source recordings')
    return selected


def main():
    base = f'https://raw.githubusercontent.com/karolpiczak/ESC-50/{REVISION}/'
    if not (FOLDER/'plan.json').exists():
        if FOLDER.exists():
            raise ValueError('Partial folder without a frozen plan')
        meta = urllib.request.urlopen(base+'meta/esc50.csv', timeout=30).read()
        license_text = urllib.request.urlopen(base+'LICENSE', timeout=30).read()
        tree = json.load(urllib.request.urlopen(
            f'https://api.github.com/repos/karolpiczak/ESC-50/git/trees/{REVISION}?recursive=1', timeout=30))
        if tree.get('truncated'):
            raise ValueError('Truncated source tree')
        lookup = {r['path']: r for r in tree['tree']}
        records = select_recordings(list(csv.DictReader(io.StringIO(meta.decode()))))
        records = [{**r, 'git_blob_sha1': lookup['audio/'+r['filename']]['sha'],
                    'source_url': base+'audio/'+r['filename']} for r in records]
        FOLDER.mkdir()
        (FOLDER/'esc50.csv').write_bytes(meta)
        (FOLDER/'LICENSE').write_bytes(license_text)
        save_json(FOLDER/'plan.json', {'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
            'source_revision': REVISION, 'tree_sha': tree['sha'], 'license': 'CC-BY-NC-3.0',
            'metadata_sha256': hashlib.sha256(meta).hexdigest(),
            'collector_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'used_for_training_or_calibration': False, 'seed': SEED, 'records': records})
    plan = json.loads((FOLDER/'plan.json').read_text())
    if plan['collector_sha256'] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError('Frozen background selection changed')
    if (FOLDER/'manifest.json').exists():
        raise ValueError('Background collection already complete')
    (FOLDER/'source').mkdir(exist_ok=True)
    (FOLDER/'pcm16').mkdir(exist_ok=True)
    rows = []
    for record in plan['records']:
        source = FOLDER/'source'/record['filename']
        if not source.exists():
            source.write_bytes(urllib.request.urlopen(record['source_url'], timeout=30).read())
            source.chmod(0o600)
        raw = source.read_bytes()
        if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() != record['git_blob_sha1']:
            raise ValueError('Public audio differs from pinned source blob')
        audio = FOLDER/'pcm16'/record['filename']
        if not audio.exists():
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(source),
                            '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(audio)], check=True)
            audio.chmod(0o600)
        rows.append({**record, 'audio': str(audio), 'audio_sha256': hashlib.sha256(audio.read_bytes()).hexdigest()})
        print('BACKGROUND', len(rows), record['category'], flush=True)
    save_json(FOLDER/'manifest.json', {'complete': True, 'plan_sha256': hashlib.sha256((FOLDER/'plan.json').read_bytes()).hexdigest(), 'rows': rows})


if __name__ == '__main__':
    main()
