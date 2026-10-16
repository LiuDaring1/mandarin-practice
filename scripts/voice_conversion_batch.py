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
import wave


def decode_audio(path):
    import numpy as np
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path),
        '-ac', '1', '-ar', '16000', '-f', 'f32le', '-'])
    return np.frombuffer(raw, dtype='<f4')


def boundary_metrics(samples, sample_rate=16000):
    """Conservative energy screen, not a listening or phoneme-quality verdict."""
    import numpy as np
    x = np.asarray(samples, dtype=float)
    if not len(x) or not np.isfinite(x).all():
        return {'silent_or_invalid': True, 'boundary_risk': True}
    peak = float(np.max(np.abs(x)))
    rms = float(np.sqrt(np.mean(x * x)))
    hop = max(1, round(sample_rate * .005))
    frames = x[:len(x) // hop * hop].reshape(-1, hop)
    levels = np.sqrt(np.mean(frames * frames, axis=1))
    reference = float(np.quantile(levels, .95)) if len(levels) else 0
    edge = max(1, round(sample_rate * .04))
    head = float(np.sqrt(np.mean(x[:edge] ** 2)))
    tail = float(np.sqrt(np.mean(x[-edge:] ** 2)))
    head_db = float(20 * np.log10(max(head, 1e-12) / max(reference, 1e-12)))
    tail_db = float(20 * np.log10(max(tail, 1e-12) / max(reference, 1e-12)))
    active = np.flatnonzero(levels > max(reference * .02, .0001))
    return {'silent_or_invalid': peak < .005 or rms < .0003,
            'boundary_risk': head_db > -32 or tail_db > -32,
            'peak': round(peak, 6), 'rms': round(rms, 6),
            'head_40ms_db': round(head_db, 2), 'tail_40ms_db': round(tail_db, 2),
            'leading_margin_ms': int(active[0] * 5) if len(active) else None,
            'trailing_margin_ms': int((len(levels) - active[-1] - 1) * 5) if len(active) else None}


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
        samples = decode_audio(path)
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
        export_id = job['id'].split('-', 2)[:2] if job['kind'] == 'sentence' else [job['id']]
        job['export_name'] = '-'.join(export_id) + '__' + args.voice + '.wav'
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
    candidates = []
    for manifest_path in sorted(args.batch.glob('staged*/*/manifest.json')):
        job_id = manifest_path.parent.name
        stage_name = manifest_path.parent.parent.name
        variant = stage_name.removeprefix('staged-') if stage_name != 'staged' else None
        suffix = '__' + variant if variant else ''
        report_path = args.batch / 'reports' / (job_id + suffix + '__boundaries.json')
        review = json.loads(report_path.read_text()) if report_path.exists() else {}
        candidates.append({'job': job_id, 'variant': variant,
                           'machine_audit_passed': review.get('passed'),
                           'review_hold_count': len(review.get('content_review_holds', []))})
    print(json.dumps({'jobs': len(jobs), 'kinds': dict(counts),
        'clips': sum(len(j['clips']) for j in jobs),
        'source_hours': round(sum(j['duration'] for j in jobs) / 3600, 2),
        'exports_present_unverified': exported,
        'candidate_versions': candidates,
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


def audit(args):
    import numpy as np
    final = stage_directory(args)
    manifest = json.loads((final / 'manifest.json').read_text())
    rows = []
    for clip in manifest['clips']:
        path = safe_path(final, clip['relative_path'])
        with wave.open(str(path), 'rb') as stream:
            valid_format = stream.getnchannels() == 1 and stream.getsampwidth() == 2 and stream.getframerate() == 16000
            if not valid_format:
                raise ValueError('Unexpected staged WAV format: ' + clip['id'])
            samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2') / 32768
        duration = len(samples) / 16000
        rows.append({'id': clip['id'], 'text': clip.get('text', ''),
            'sha256_matches': digest(path) == clip['sha256'],
            'duration_matches': abs(duration - clip['audio']['duration']) <= .001,
            **boundary_metrics(samples)})
    issues = [r for r in rows if r['silent_or_invalid'] or r['boundary_risk']
              or not r['sha256_matches'] or not r['duration_matches']]
    holds = []
    hold_path = args.batch / 'reports' / (args.job + '__holds.json')
    if hold_path.exists():
        hold_data = json.loads(hold_path.read_text())
        job = job_for(args)
        if hold_data['export_sha256'] != digest(args.batch / 'exports' / job['export_name']):
            raise ValueError('Review holds refer to a different export')
        holds = hold_data['clips']
        if not {h['id'] for h in holds}.issubset({c['id'] for c in rows}):
            raise ValueError('Review holds contain unknown clips')
    result = {'job': args.job, 'variant': getattr(args, 'variant', None),
        'checked': len(rows), 'passed': not issues and not holds,
        'silent': [r['id'] for r in rows if r['silent_or_invalid']],
        'boundary_risks': [r['id'] for r in rows if r['boundary_risk']],
        'content_review_holds': holds,
        'phonetic_or_listening_review': False,
        'note': 'Energy and file-integrity screening only; cannot prove pronunciation.',
        'clips': rows}
    suffix = '__' + args.variant if getattr(args, 'variant', None) else ''
    write_json(args.batch / 'reports' / (args.job + suffix + '__boundaries.json'), result)
    print(json.dumps({k: v for k, v in result.items() if k != 'clips'}, ensure_ascii=False))
    return result


def stage_directory(args):
    variant = getattr(args, 'variant', None)
    folder = 'staged' if not variant else 'staged-' + variant
    return safe_path(args.batch, folder + '/' + args.job)


def timing_after_repairs(timing, repairs):
    """Ignore a failed page window only when its entire interval was reconverted."""
    if timing['stable']:
        return {'stable': True, 'replaced_windows': []}
    windows = timing.get('windows', [])
    kept, replaced = [], []
    for window in windows:
        start = window['source_start']
        if any(r['source_origin_seconds'] <= start and
               start + 8 <= r['source_origin_seconds'] + r['duration'] for r in repairs):
            replaced.append(start)
        else:
            kept.append(window)
    stable = len(kept) >= 3 and bool(replaced) and all(w['correlation'] >= .65 for w in kept)
    lags = [w['lag_ms'] for w in kept]
    stable = stable and max(lags) - min(lags) <= 120 and max(abs(x) for x in lags) < 950
    return {'stable': bool(stable), 'replaced_windows': replaced}


def cut(args):
    if not args.timing_reviewed:
        raise ValueError('Review beginning/middle/end timing before --timing-reviewed')
    job = job_for(args)
    report = inspect_export(args)
    if not report['duration_within_100ms']:
        raise ValueError('Duration changed: realign before cutting')
    repairs = []
    for repair_id in getattr(args, 'repair', []):
        repair_args = argparse.Namespace(batch=args.batch, job=repair_id)
        repair_job = job_for(repair_args)
        if repair_job.get('parent_job') != job['id']:
            raise ValueError('Repair parent does not match target job')
        repair_report = inspect_export(repair_args)
        if not repair_report['duration_within_100ms'] or not repair_report['timing']['stable']:
            raise ValueError('Repair timing is uncertain')
        if digest(Path(repair_job['source'])) != repair_job['source_sha256']:
            raise ValueError('Repair source changed')
        repairs.append((repair_job, repair_report))
    accepted_timing = timing_after_repairs(report['timing'], [j for j, _ in repairs])
    if not accepted_timing['stable']:
        raise ValueError('Local timing changed or uncertain: realign before cutting')
    offset = args.offset_ms / 1000
    if abs(args.offset_ms - report['timing']['median_lag_ms']) > 30:
        raise ValueError('Offset differs from measured timing; review alignment')
    source = Path(job['source'])
    if digest(source) != job['source_sha256']:
        raise ValueError('Original source changed since queue creation')
    # Stage each job atomically; interrupted jobs can retry without partial publication.
    final = stage_directory(args)
    if final.exists():
        raise ValueError('Staged job already exists; inspect it rather than overwriting')
    head = getattr(args, 'head_pad_ms', 0) / 1000
    tail = getattr(args, 'tail_pad_ms', 0) / 1000
    if not 0 <= head <= .3 or not 0 <= tail <= .3:
        raise ValueError('Padding must be between 0 and 300 ms')
    plan = {}
    corrections = {}
    bounds_file = getattr(args, 'bounds_file', None)
    if bounds_file:
        bounds = json.loads(bounds_file.read_text())
        if bounds['job'] != job['id'] or bounds['export_sha256'] != report['export_sha256']:
            raise ValueError('Boundary corrections refer to another job or export')
        corrections = bounds['clips']
        if not set(corrections).issubset({c['id'] for c in job['clips']}):
            raise ValueError('Boundary corrections contain unknown clips')
        if any(set(c) != {'start', 'end'} for c in corrections.values()):
            raise ValueError('Boundary corrections may only change start and end')

    def add_plan(source_job, source_report, shift):
        clips = [{**c, **(corrections.get(c['id'], {}) if source_job['id'] == job['id'] else {})}
                 for c in source_job['clips']]
        for index, clip in enumerate(clips):
            safe_path(final, clip['relative_path'])
            start, end = clip['start'] + shift, clip['end'] + shift
            left, right = 0, source_report['audio']['duration']
            if index and clips[index - 1]['end'] <= clip['start']:
                left = (clips[index - 1]['end'] + clip['start']) / 2 + shift
            if index + 1 < len(clips) and clip['end'] <= clips[index + 1]['start']:
                right = (clip['end'] + clips[index + 1]['start']) / 2 + shift
            start, end = max(left, start - head), min(right, end + tail)
            if not 0 <= start < end <= source_report['audio']['duration']:
                raise ValueError('Invalid clip boundary: ' + clip['id'])
            plan[clip['id']] = {'clip': clip, 'start': start, 'end': end,
                               'export': source_report['export'], 'job': source_job['id']}

    add_plan(job, report, offset)
    for repair_job, repair_report in repairs:
        originals = {c['id']: c for c in job['clips']}
        for c in repair_job['clips']:
            if c['id'] not in originals or c['relative_path'] != originals[c['id']]['relative_path']:
                raise ValueError('Repair clip mapping does not match parent')
        add_plan(repair_job, repair_report, repair_report['timing']['median_lag_ms'] / 1000)
    # Never publish an all-silent replacement, even if page-level timing passed.
    audio_cache = {p: decode_audio(p) for p in {v['export'] for v in plan.values()}}
    original_audio = decode_audio(source) if getattr(args, 'conversion_only', False) else None
    for item in plan.values():
        segment = audio_cache[item['export']][round(item['start'] * 16000):round(item['end'] * 16000)]
        if boundary_metrics(segment)['silent_or_invalid']:
            if original_audio is not None:
                core = next(c for c in job['clips'] if c['id'] == item['clip']['id'])
                before = original_audio[round(core['start'] * 16000):round(core['end'] * 16000)]
                if boundary_metrics(before)['silent_or_invalid']:
                    continue
            raise ValueError('Silent or missing speech in converted clip: ' + item['clip']['id'])
    final.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=final.parent) as temporary:
        staging = Path(temporary) / 'output'
        staging.mkdir()
        outputs = []
        for clip in job['clips']:
            item = plan[clip['id']]
            target = safe_path(staging, clip['relative_path'])
            target.parent.mkdir(parents=True, exist_ok=True)
            import numpy as np
            segment = audio_cache[item['export']][round(item['start'] * 16000):round(item['end'] * 16000)]
            pcm = np.clip(np.rint(segment * 32768), -32768, 32767).astype('<i2')
            with wave.open(str(target), 'wb') as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(16000)
                stream.writeframes(pcm.tobytes())
            info = {'duration': len(pcm) / 16000, 'sample_rate': 16000, 'channels': 1}
            if abs(info['duration'] - (item['end'] - item['start'])) > .02:
                raise ValueError('Unexpected cut duration: ' + clip['id'])
            outputs.append({**clip, 'converted_start': item['start'],
                            'converted_end': item['end'], 'conversion_job': item['job'],
                            'export': item['export'],
                            'boundary_correction': corrections.get(clip['id']),
                            'sha256': digest(target), 'audio': info})
        write_json(staging / 'manifest.json', {'job': job['id'], 'voice': job['voice'],
            'timing_reviewed': True, 'offset_ms': args.offset_ms,
            'head_pad_ms': head * 1000, 'tail_pad_ms': tail * 1000,
            'accepted_timing': accepted_timing,
            'boundary_corrections': corrections,
            'repairs': getattr(args, 'repair', []),
            'conversion_only': getattr(args, 'conversion_only', False),
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
    for name, func in [('stage-input', stage_input), ('inspect', inspect_export), ('cut', cut), ('audit', audit)]:
        p = sub.add_parser(name)
        p.add_argument('--job', required=True)
        if name in {'cut', 'audit'}:
            p.add_argument('--variant')
        if name == 'cut':
            p.add_argument('--timing-reviewed', action='store_true')
            p.add_argument('--offset-ms', type=float, required=True)
            p.add_argument('--head-pad-ms', type=float, default=0)
            p.add_argument('--tail-pad-ms', type=float, default=0)
            p.add_argument('--repair', action='append', default=[])
            p.add_argument('--bounds-file', type=Path)
            p.add_argument('--conversion-only', action='store_true',
                           help='Allow silence already present at the identical source interval')
        p.set_defaults(func=func)
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
