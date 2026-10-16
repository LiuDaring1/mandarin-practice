import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import wave

import numpy as np
import pytest


spec = importlib.util.spec_from_file_location(
    'voice_conversion_batch', Path(__file__).parents[1] / 'scripts/voice_conversion_batch.py')
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


def test_prepare_filters_exclusions_and_preserves_source(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    source = tmp_path / 'raw/page.mp3'
    source.parent.mkdir()
    source.write_bytes(b'original recording')
    with sqlite3.connect(data / 'corpus.sqlite3') as db:
        db.executescript('''
            CREATE TABLE source_pages(id,source_key,audio_path,audio_duration_ms,table_kind,page_no);
            CREATE TABLE entries(item_id,source_page_id,word_raw,page_position);
            CREATE TABLE segments(item_id,clip_path,start_ms,end_ms);
            CREATE TABLE excluded_items(item_id);
            INSERT INTO source_pages VALUES(1,'t1-p001','raw/page.mp3',12000,'table1',1);
            INSERT INTO entries VALUES('keep',1,'新闻',1),('excluded',1,'错误',2);
            INSERT INTO segments VALUES('keep','derived/keep.wav',500,1200),
                                       ('excluded','derived/excluded.wav',2000,2600);
            INSERT INTO excluded_items VALUES('excluded');
        ''')
    args = argparse.Namespace(batch=tmp_path / 'batch', data=data, source_data=tmp_path,
                              sentence_sources=None, voice='news-female')
    before = batch.digest(data / 'corpus.sqlite3')
    batch.prepare(args)
    job = batch.queue(args)[0]
    assert [clip['id'] for clip in job['clips']] == ['keep']
    assert batch.digest(data / 'corpus.sqlite3') == before
    args.job = job['id']
    batch.stage_input(args)
    assert (args.batch / 'inputs/t1-p001.mp3').read_bytes() == source.read_bytes()
    source.write_bytes(b'changed recording')
    with pytest.raises(ValueError, match='changed'):
        batch.stage_input(args)
    with pytest.raises(ValueError, match='already exists'):
        batch.prepare(args)


def test_path_escape_rejected(tmp_path):
    with pytest.raises(ValueError):
        batch.safe_path(tmp_path / 'stage', '../../live.wav')


def test_cut_requires_timing_review(tmp_path):
    with pytest.raises(ValueError, match='Review'):
        batch.cut(argparse.Namespace(batch=tmp_path, timing_reviewed=False))


@pytest.mark.parametrize('report,offset,error', [
    ({'duration_within_100ms': False}, 0, 'Duration changed'),
    ({'duration_within_100ms': True, 'timing': {'stable': False}}, 0, 'Local timing'),
    ({'duration_within_100ms': True, 'timing': {'stable': True, 'median_lag_ms': 90}},
     0, 'Offset differs'),
])
def test_cut_blocks_bad_timing_without_writing(tmp_path, monkeypatch, report, offset, error):
    monkeypatch.setattr(batch, 'job_for', lambda _: {'id': 'page'})
    monkeypatch.setattr(batch, 'inspect_export', lambda _: report)
    with pytest.raises(ValueError, match=error):
        batch.cut(argparse.Namespace(batch=tmp_path, timing_reviewed=True, offset_ms=offset))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg required')
def test_energy_alignment_detects_delay(tmp_path):
    # Varying speech-like bursts, with a known 90 ms delay and changed gain.
    rate = 16000
    rng = np.random.default_rng(123)
    a = np.zeros(rate * 15, dtype=np.float32)
    for start, length in zip(rng.integers(0, len(a) - rate, 65), rng.integers(800, 6000, 65)):
        a[start:start + length] += rng.normal(0, .06, length)
    shifted = np.concatenate([np.zeros(1440), a[:-1440]]) * .7
    paths = [tmp_path / 'source.wav', tmp_path / 'converted.wav']
    for path, samples in zip(paths, [a, shifted]):
        with wave.open(str(path), 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes((samples * 32767).astype('<i2').tobytes())
    result = batch.timing_analysis(*paths)
    assert result['stable']
    assert abs(result['median_lag_ms'] - 90) <= 10


def test_boundary_screen_rejects_silent_and_truncated_audio():
    assert batch.boundary_metrics(np.zeros(16000))['silent_or_invalid']
    t = np.arange(16000) / 16000
    tone = .2 * np.sin(2 * np.pi * 220 * t)
    assert batch.boundary_metrics(tone)['boundary_risk']
    guarded = np.concatenate([np.zeros(1600), tone, np.zeros(1600)])
    report = batch.boundary_metrics(guarded)
    assert not report['silent_or_invalid']
    assert not report['boundary_risk']
    assert report['leading_margin_ms'] >= 95
    assert report['trailing_margin_ms'] >= 95


def test_cut_rejects_local_dropout_even_when_page_timing_passes(tmp_path, monkeypatch):
    source = tmp_path / 'original.wav'
    source.write_bytes(b'protected original')
    job = {'id': 'page', 'source': str(source), 'source_sha256': batch.digest(source),
           'clips': [{'id': 'word', 'relative_path': 'derived/word.wav', 'start': .2, 'end': .8}]}
    report = {'duration_within_100ms': True, 'audio': {'duration': 1},
              'timing': {'stable': True, 'median_lag_ms': 0}, 'export': 'converted.wav'}
    monkeypatch.setattr(batch, 'job_for', lambda _: job)
    monkeypatch.setattr(batch, 'inspect_export', lambda _: report)
    monkeypatch.setattr(batch, 'decode_audio', lambda _: np.zeros(16000))
    with pytest.raises(ValueError, match='Silent or missing speech'):
        batch.cut(argparse.Namespace(batch=tmp_path / 'batch', job='page',
                                    timing_reviewed=True, offset_ms=0))
    assert not (tmp_path / 'batch').exists()
    assert source.read_bytes() == b'protected original'


def test_repair_must_cover_entire_failed_window_and_leave_valid_evidence():
    timing = {'stable': False, 'windows': [
        {'source_start': 0, 'lag_ms': 70, 'correlation': .9},
        {'source_start': 10, 'lag_ms': 70, 'correlation': .9},
        {'source_start': 20, 'lag_ms': -20, 'correlation': .3},
        {'source_start': 30, 'lag_ms': 80, 'correlation': .9},
    ]}
    assert not batch.timing_after_repairs(timing, [])['stable']
    assert not batch.timing_after_repairs(timing, [
        {'source_origin_seconds': 21, 'duration': 8}])['stable']
    result = batch.timing_after_repairs(timing, [
        {'source_origin_seconds': 19, 'duration': 10}])
    assert result == {'stable': True, 'replaced_windows': [20]}
    assert not batch.timing_after_repairs(timing, [
        {'source_origin_seconds': 0, 'duration': 40}])['stable']


def test_review_hold_blocks_a_clean_energy_screen(tmp_path):
    root = tmp_path / 'batch'
    staged = root / 'staged-safe/page'
    staged.mkdir(parents=True)
    export = root / 'exports/page.wav'
    export.parent.mkdir()
    t = np.arange(8000) / 16000
    samples = np.concatenate([np.zeros(1600), .2 * np.sin(2 * np.pi * 220 * t), np.zeros(1600)])
    for path in [staged / 'word.wav', export]:
        with wave.open(str(path), 'wb') as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes((samples * 32767).astype('<i2').tobytes())
    batch.write_json(staged / 'manifest.json', {'clips': [{'id': 'word',
        'relative_path': 'word.wav', 'sha256': batch.digest(staged / 'word.wav'),
        'audio': {'duration': len(samples) / 16000}}]})
    batch.write_json(root / 'queue.json', {'jobs': [{'id': 'page', 'export_name': 'page.wav'}]})
    batch.write_json(root / 'reports/page__holds.json', {'export_sha256': batch.digest(export),
        'clips': [{'id': 'word', 'reason': 'Word-to-audio mapping needs review'}]})
    result = batch.audit(argparse.Namespace(batch=root, job='page', variant='safe'))
    assert not result['passed']
    assert result['silent'] == [] and result['boundary_risks'] == []
    assert result['content_review_holds'][0]['id'] == 'word'
