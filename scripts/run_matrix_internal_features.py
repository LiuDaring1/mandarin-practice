"""Byte-verified internal-disk execution after external device read failures.

No numerical/model changes: the one absolute-path manifest is redirected to
byte-identical copies. Three old audio feature anchors must replay before the
new cohort is inferred. All caches/results are kept on the internal disk.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT=Path.home()/'.cache/nasal-api-recovery/matrix-control-v1/execution-root'
BASE=Path('data/derived/nasal-acoustic-validation')


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while block:=f.read(1024*1024):h.update(block)
    return h.hexdigest()


def prepare():
    import run_matrix_validation as run
    plan=run.checked();parent=run.pipeline.checked();original=Path.cwd();sources={}
    def copy(source,relative=None):
        source=Path(source);relative=relative or source.resolve().relative_to(original)
        destination=ROOT/relative;destination.parent.mkdir(parents=True,exist_ok=True)
        before=digest(source)
        if destination.exists():
            if digest(destination)!=before:raise ValueError('Different internal copy')
        else:
            with source.open('rb') as src,destination.open('wb') as dst:
                while block:=src.read(1024*1024):dst.write(block)
                dst.flush();os.fsync(dst.fileno())
            destination.chmod(0o600)
        if digest(destination)!=before or digest(source)!=before:raise ValueError('Copy changed')
        sources[str(relative)]=before
    for top in ('scripts','src'):
        for path in Path(top).rglob('*.py'):copy(path)
    vad=BASE/'silero-vad-v1';v=json.loads((vad/'source.json').read_text());copy(vad/'source.json')
    for name in v['files']:copy(vad/name)
    xeus=BASE/'xeus-v1'
    for name in ('model-source.json','runtime-source.json'):copy(xeus/name)
    for p in (xeus/'runtime').rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts:copy(p)
    hubert=BASE/'chinese-hubert-model-v1';h=json.loads((hubert/'source.json').read_text());copy(hubert/'source.json')
    for p,spec in h['sources'].items():
        if digest(p)!=spec['sha256']:raise ValueError('Frozen encoder source changed')
        copy(p)
    for name in ('plan.json','dataset.json'):copy(run.FOLDER/name)
    for name in ('plan.json','anchor-features.npz'):copy(run.pipeline.FOLDER/name)
    anchors=[]
    for i,row in enumerate(parent['anchors']):
        relative=Path('anchor-audio')/(str(i)+'.wav');copy(row['audio'],relative)
        anchors.append({**row,'audio':str(ROOT/relative)})
    report={'original_root':str(original),'sources':sources,'anchors':anchors,
            'plan_sha256':digest(run.FOLDER/'plan.json'), 'source':str(Path(__file__).resolve()),
            'source_sha256':digest(__file__),'changed_math_or_parameters':False,
            'initial_feature_failure':'External device not configured during VAD source verification; no new features produced.'}
    destination=ROOT/'relocation.json'
    if destination.exists():raise ValueError('Relocation already frozen')
    from nasal_validation_execution import durable_json
    durable_json(destination,report)
    print('INTERNAL EXECUTION COPY VERIFIED',len(sources),'files',flush=True)


def run():
    import numpy as np
    import run_matrix_validation as matrix
    import run_latic_validation as pipeline
    import chinese_hubert_features as hubert
    from nasal_validation_execution import durable_json
    from probe_nasal_pairs import save_npz
    if Path.cwd()!=ROOT:raise ValueError('Use verified internal execution root')
    relocation=json.loads((ROOT/'relocation.json').read_text())
    for p,d in relocation['sources'].items():
        if digest(ROOT/p)!=d:raise ValueError('Internal copy changed: '+p)
    original=Path(relocation['original_root'])
    # Only the old manifest's absolute filesystem references are redirected.
    # Source manifest bytes, model weights, preprocessing and runtime identity
    # remain unchanged; the anchor replay below verifies the numerical path.
    def relocated(value):
        p=Path(value)
        return ROOT/p.relative_to(original) if p.is_absolute() and p.is_relative_to(original) else p
    hubert.Path=relocated
    plan=json.loads((matrix.FOLDER/'plan.json').read_text());data=json.loads((matrix.FOLDER/'dataset.json').read_text())
    pipeline.FOLDER=matrix.FOLDER
    anchor_report=matrix.MIRROR/'relocation-preflight.json'
    if anchor_report.exists():raise ValueError('Completed relocation run exists')
    values,details=pipeline.extract_rows(relocation['anchors'],matrix.MIRROR/'relocation-anchor-cache',plan)
    with np.load(BASE/'latic-pipeline-v1/anchor-features.npz',allow_pickle=False) as old:
        deltas={k:float(np.max(np.abs(values[k]-old[k]))) for k in ('paired','temporal')}
        if not values['available'].all() or any(v>1e-4 for v in deltas.values()) or not np.array_equal(values['present'],old['present']):
            raise ValueError('Relocation feature/VAD replay failed')
    durable_json(anchor_report,{'complete':True,'feature_max_differences':deltas,'vad_exact':True,
        'relocation_sha256':digest(ROOT/'relocation.json'),**details})
    values,details=pipeline.extract_rows(data['rows'],matrix.MIRROR/'feature-cache',plan)
    save_npz(matrix.MIRROR/'features.npz',**values)
    durable_json(matrix.MIRROR/'feature-report.json',{'complete':True,'plan_sha256':digest(matrix.FOLDER/'plan.json'),
        'dataset_sha256':digest(matrix.FOLDER/'dataset.json'),'features_sha256':digest(matrix.MIRROR/'features.npz'),
        **details,'available_by_block':dict(zip(pipeline.BLOCKS,values['available'].sum(axis=0).tolist())),
        'relocation_sha256':digest(ROOT/'relocation.json'),'relocation_preflight_sha256':digest(anchor_report)})
    print('INTERNAL MATRIX FEATURES COMPLETE',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','run']);args=p.parse_args()
    globals()[args.mode]()
