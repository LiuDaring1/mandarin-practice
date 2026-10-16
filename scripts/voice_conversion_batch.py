"""Local queue and staging for Jianying voice conversion; never alters live data."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def probe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_format',
                             '-show_streams', '-of', 'json', str(path)],
                            check=True, capture_output=True, text=True)
    info = json.loads(result.stdout)
    audio = next(s for s in info['streams'] if s['codec_type'] == 'audio')
    return {'duration': float(info['format']['duration']),
            'sample_rate': int(audio['sample_rate']), 'channels': audio['channels']}


def timing_analysis(original, converted):
    """Compare local speech energy at 11 positions; this cannot assess pronunciation."""
    import numpy as np
    from scipy.signal import correlate

    def envelope(path):
        raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path),
            '-ac', '1', '-ar', '16000', '-f', 'f32le', '-'])
        samples = np.frombuffer(raw, dtype='<f4')
        frames = samples[:len(samples) // 160 * 160].reshape(-1, 160)
        return np.sqrt((frames * frames).mean(axis=1))

    a, b = envelope(original), envelope(converted)
    size, radius = 800, 100
    if min(len(a), len(b)) < size + 2 * radius:
        return {'stable': False, 'reason': 'Too short for page timing analysis'}
    windows = []
    for lo in np.linspace(radius, min(len(a), len(b)) - size - radius, 11, dtype=int):
        x = a[lo:lo + size]
        x = x - x.mean()
        y = b[lo - radius:lo + size + radius]
        corr = correlate(y - y.mean(), x, mode='valid')
        scores = np.array([corr[i] / (np.linalg.norm(x) *
            np.linalg.norm(y[i:i + size] - y[i:i + size].mean()) + 1e-12)
            for i in range(len(corr))])
        best = int(scores.argmax())
        windows.append({'source_start': float(lo / 100), 'lag_ms': (best - radius) * 10,
                        'correlation': round(float(scores[best]), 4)})
    lags = [w['lag_ms'] for w in windows]
    return {'stable': min(w['correlation'] for w in windows) >= .65 and
            max(lags) - min(lags) <= 120 and max(abs(x) for x in lags) < 950,
            'median_lag_ms': float(np.median(lags)), 'windows': windows,
            'note': 'Energy correlation estimates timing only; inspect clip boundaries separately.'}


def prepare(args):
    batch = args.batch.resolve()
    if (batch / 'queue.json').exists():
        raise ValueError('Queue already exists; use status to resume, do not reset it.')
    data = args.data.resolve()
    jobs = {}
    with sqlite3.connect((data / 'corpus.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('''SELECT p.source_key, p.audio_path, p.audio_duration_ms,
                    e.item_id,e.word_raw,s.clip_path,s.start_ms,s.end_ms
                FROM entries e JOIN source_pages p ON p.id=e.source_page_id
                JOIN segments s USING(item_id)
                LEFT JOIN excluded_items x ON x.item_id=e.item_id
                WHERE x.item_id IS NULL AND s.clip_path IS NOT NULL
                ORDER BY p.table_kind,p.page_no,e.page_position''')
        for row in rows:
            key = row['source_key']
            if key not in jobs:
                source = (args.source_data / row['audio_path']).resolve()
                if not source.is_file():
                    raise FileNotFoundError(source)
                jobs[key] = {'id': key, 'kind': 'word', 'source': str(source),
                             'source_sha256': digest(source),
                             'duration': row['audio_duration_ms'] / 1000, 'clips': []}
            jobs[key]['clips'].append({'id': row['item_id'], 'text': row['word_raw'],
                                      'relative_path': row['clip_path'],
                                      'start': row['start_ms'] / 1000,
                                      'end': row['end_ms'] / 1000})
    manifest = data / 'derived/sentence-practice-v1/clip_manifest.json'
    if args.sentence_sources:
        by_name = defaultdict(list)
        for path in args.sentence_sources.rglob('*'):
            if path.is_file() and path.suffix.lower() in {'.mp3', '.mp4', '.wav', '.m4a'}:
                by_name[path.name].append(path.resolve())
        for clip in json.loads(manifest.read_text()):
            key = 'sentence-' + clip['article_id']
            if key not in jobs:
                matches = by_name[clip['source_file']]
                if len(matches) != 1:
                    raise ValueError(f"Expected one source for {clip['source_file']}: {matches}")
                source = matches[0]
                jobs[key] = {'id': key, 'kind': 'sentence', 'source': str(source),
                             'source_sha256': digest(source),
                             'duration': probe(source)['duration'], 'clips': []}
            jobs[key]['clips'].append({'id': clip['sentence_id'],
                'relative_path': 'derived/sentence-practice-v1/' + clip['wav_rel'],
                'start': clip['src_start'], 'end': clip['src_end']})
    for job in jobs.values():
        job['voice'] = args.voice
        job['export_name'] = job['id'] + '__' + args.voice + '.wav'
    write_json(batch / 'queue.json', {'version': 1, 'jobs': list(jobs.values())})
    for name in ['inputs', 'exports', 'reports', 'staged']:
        (batch / name).mkdir(exist_ok=True)
    status(args)


def queue(args):
    return json.loads((args.batch / 'queue.json').read_text())['jobs']


def job_for(args):
    return next(job for job in queue(args) if job['id'] == args.job)


def status(args):
    jobs = queue(args)
    counts = Counter(job['kind'] for job in jobs)
    exported = [j['id'] for j in jobs if (args.batch / 'exports' / j['export_name']).is_file()]
    print(json.dumps({'jobs': len(jobs), 'kinds': dict(counts),
        'clips': sum(len(j['clips']) for j in jobs),
        'source_hours': round(sum(j['duration'] for j in jobs) / 3600, 2),
        'exports_present_unverified': exported,
        'staged': [j['id'] for j in jobs if (args.batch / 'staged' / j['id'] / 'manifest.json').exists()]}, ensure_ascii=False))


def stage_input(args):
    job = job_for(args)
    source = Path(job['source'])
    if digest(source) != job['source_sha256']:
        raise ValueError('Original source changed since queue creation')
    target = args.batch / 'inputs' / (job['id'] + source.suffix)
    if target.exists() and digest(target) != job['source_sha256']:
        raise ValueError('Conflicting staged input')
    if not target.exists():
        shutil.copy2(source, target)
    print(target.resolve())
    print('Export as:', (args.batch / 'exports' / job['export_name']).resolve())


def inspect_export(args):
    job = job_for(args)
    path = args.batch / 'exports' / job['export_name']
    info = probe(path)
    delta = info['duration'] - job['duration']
    report = {'job': job['id'], 'voice': job['voice'], 'export': str(path.resolve()),
              'export_sha256': digest(path), 'audio': info,
              'source_duration': job['duration'], 'duration_delta': round(delta, 6),
              'duration_within_100ms': abs(delta) <= .1,
              'timing': timing_analysis(Path(job['source']), path),
              'timing_reviewed': False, 'pronunciation_reviewed': False,
              'note': 'Equal total length does not prove local timing or pronunciation.'}
    write_json(args.batch / 'reports' / (job['id'] + '.json'), report)
    print(json.dumps(report, ensure_ascii=False))
    return report


def safe_path(base, relative):
    target = (base / relative).resolve()
    target.relative_to(base.resolve())
    return target


def cut(args):
    if not args.timing_reviewed:
        raise ValueError('Review beginning/middle/end timing before --timing-reviewed')
    job = job_for(args)
    report = inspect_export(args)
    if not report['duration_within_100ms']:
        raise ValueError('Duration changed: realign before cutting')
    if not report['timing']['stable']:
        raise ValueError('Local timing changed or uncertain: realign before cutting')
    offset = args.offset_ms / 1000
    if abs(args.offset_ms - report['timing']['median_lag_ms']) > 30:
        raise ValueError('Offset differs from measured timing; review alignment')
    source = Path(job['source'])
    if digest(source) != job['source_sha256']:
        raise ValueError('Original source changed since queue creation')
    # Stage each job atomically; interrupted jobs can retry without partial publication.
    final = args.batch / 'staged' / job['id']
    if final.exists():
        raise ValueError('Staged job already exists; inspect it rather than overwriting')
    for clip in job['clips']:
        safe_path(final, clip['relative_path'])
        if not 0 <= clip['start'] + offset < clip['end'] + offset <= report['audio']['duration']:
            raise ValueError('Invalid clip boundary: ' + clip['id'])
    with tempfile.TemporaryDirectory(dir=args.batch / 'staged') as temporary:
        staging = Path(temporary) / 'output'
        staging.mkdir()
        outputs = []
        for clip in job['clips']:
            target = safe_path(staging, clip['relative_path'])
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-i', report['export'],
                '-ss', str(clip['start'] + offset), '-t', str(clip['end'] - clip['start']),
                '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(target)], check=True)
            info = probe(target)
            if abs(info['duration'] - (clip['end'] - clip['start'])) > .02:
                raise ValueError('Unexpected cut duration: ' + clip['id'])
            outputs.append({**clip, 'converted_start': clip['start'] + offset,
                            'sha256': digest(target), 'audio': info})
        write_json(staging / 'manifest.json', {'job': job['id'], 'voice': job['voice'],
            'timing_reviewed': True, 'offset_ms': args.offset_ms,
            'pronunciation_reviewed': False, 'clips': outputs})
        staging.rename(final)
    print(f'Staged {len(outputs)} clips at {final.resolve()}; live application unchanged.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--data', type=Path, default=Path('data'))
    p.add_argument('--source-data', type=Path, required=True)
    p.add_argument('--sentence-sources', type=Path)
    p.add_argument('--voice', choices=['news-female', 'news-male'], default='news-female')
    p.set_defaults(func=prepare)
    sub.add_parser('status').set_defaults(func=status)
    for name, func in [('stage-input', stage_input), ('inspect', inspect_export), ('cut', cut)]:
        p = sub.add_parser(name)
        p.add_argument('--job', required=True)
        if name == 'cut':
            p.add_argument('--timing-reviewed', action='store_true')
            p.add_argument('--offset-ms', type=float, required=True)
        p.set_defaults(func=func)
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
