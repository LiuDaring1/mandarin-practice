"""CPU-only preflight after failed MPS parity; preserve failure, check grid/replay."""
import json
from pathlib import Path
import time

import numpy as np

from chinese_hubert_features import ChineseHubert, pool_halves
from fetch_chinese_hubert import FOLDER as MODEL
from nasal_acoustics import read_audio
from probe_xeus_encoder_context import load_base,engine
from train_nasal_feature_probe import save_json
from zipa_context import context_interval


def main():
    import torch
    folder=engine.BASE/'chinese-hubert-preflight-v1';output=folder/'report.json'
    if output.exists(): raise ValueError('HuBERT preflight frozen')
    started=time.monotonic(); model=ChineseHubert('cpu')
    rows,_,_,_=load_base('existing');row=next(r for r in rows if r['split']=='train')
    if engine.sha(row['audio'])!=row['audio_sha256']: raise ValueError('Preflight audio changed')
    samples=read_audio(Path(row['audio']),max_seconds=180);a,b=context_interval(len(samples),row['bounds']['syllable'])
    # One fixed training target only; no evaluation result enters this check.
    audio=samples[a:b];cpu=model.infer(audio);again=model.infer(audio)
    repeated=float(np.max(np.abs(cpu-again)))
    if repeated>1e-6: raise ValueError(f'CPU repeatability mismatch: {repeated}')
    pooled=pool_halves(cpu,row['bounds'],a,b-a)
    silence=model.infer(np.zeros(16000,dtype=np.float32))
    maximum_started=time.monotonic()
    maximum=model.infer(np.random.default_rng(72).normal(0,.01,320000).astype(np.float32))
    maximum_elapsed=time.monotonic()-maximum_started
    if silence.shape!=(4,49,1024) or maximum.shape!=(4,999,1024) or pooled.shape!=(4,2048):
        raise ValueError('Time grid/pooling shape mismatch')
    paths=[Path('scripts')/n for n in ('fetch_chinese_hubert.py','chinese_hubert_features.py','preflight_chinese_hubert.py')]+[MODEL/'source.json',folder/'mps-parity-failed/failure.json']
    paths+=sorted((folder/'mps-parity-failed').glob('*.py'))
    folder.mkdir(exist_ok=True)
    save_json(output,{'complete':True,'model':model.identity,'sources':{str(p):engine.sha(p) for p in paths},
        'one_training_target_only':True,'audio_sha256':row['audio_sha256'],'nominal_first_center_seconds':.0125,
        'training_parent_frames':cpu.shape[1],'cpu_repeat_max_difference':repeated,
        'silence_finite':True,'maximum_20s_frames':maximum.shape[1],'maximum_20s_elapsed_seconds':maximum_elapsed,
        'mps_parity_passed':False,'mps_used_for_experiment':False,
        'elapsed_seconds':time.monotonic()-started,'evaluation_used':False,'silence_is_not_correctness_evidence':True})
    print('HUBERT CPU PREFLIGHT COMPLETE','repeat_delta',repeated,'20s inference_seconds',maximum_elapsed,flush=True)


if __name__=='__main__': main()
