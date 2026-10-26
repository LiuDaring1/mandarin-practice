"""Pinned Silero VAD ONNX input protocol and a local speech-presence gate.

Protocol adapted from the MIT-licensed snakers4/silero-vad OnnxWrapper.
https://github.com/snakers4/silero-vad
Speech presence is not target identity, nasal correctness, or a diagnosis.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import urllib.request

import numpy as np

from train_nasal_feature_probe import save_json

REVISION='066409f3d9db45a30d21dfcbf9147826ffdd7052'
BLOB='80c5592ef1f4c9ede3e357bbd02eb863358a6a9d'
FOLDER=Path('data/derived/nasal-acoustic-validation/silero-vad-v1')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fetch():
    if (FOLDER/'source.json').exists():
        raise ValueError('Silero source already collected')
    FOLDER.mkdir(exist_ok=True)
    base=f'https://raw.githubusercontent.com/snakers4/silero-vad/{REVISION}/'
    for source,name in [('src/silero_vad/data/silero_vad.onnx','silero_vad.onnx'),
                        ('src/silero_vad/utils_vad.py','utils_vad.py'),('LICENSE','LICENSE')]:
        path=FOLDER/name
        if not path.exists():
            path.write_bytes(urllib.request.urlopen(base+source,timeout=30).read());path.chmod(0o600)
    model=FOLDER/'silero_vad.onnx';raw=model.read_bytes()
    if len(raw)!=2327524 or hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=BLOB:
        raise ValueError('Silero model does not match the pinned Git blob')
    save_json(FOLDER/'source.json',{'revision':REVISION,'license':'MIT','git_blob_sha1':BLOB,
        'files':{p.name:sha(p) for p in [model,FOLDER/'utils_vad.py',FOLDER/'LICENSE']}})


def probabilities(session, samples):
    """Reset state per recording, carry 64 samples, and pad only the last chunk."""
    x=np.asarray(samples,dtype=np.float32)
    if x.ndim!=1 or not len(x) or not np.isfinite(x).all():
        raise ValueError('Expected finite mono waveform')
    state=np.zeros((2,1,128),dtype=np.float32);context=np.zeros((1,64),dtype=np.float32)
    output=[]
    for start in range(0,len(x),512):
        chunk=x[start:start+512]
        chunk=np.pad(chunk,(0,512-len(chunk)))[None]
        model_input=np.concatenate([context,chunk],axis=1)
        value,state=session.run(None,{'input':model_input,'state':state,'sr':np.array(16000,dtype=np.int64)})
        if value.shape!=(1,1) or state.shape!=(2,1,128) or not np.isfinite(state).all():
            raise RuntimeError('Unexpected VAD state/output shape')
        score=float(value[0,0])
        if not np.isfinite(score) or not 0<=score<=1:
            raise RuntimeError('Invalid VAD probability')
        output.append(score);context=model_input[:,-64:].copy()
    return np.array(output,dtype=np.float32)


def target_speech(scores,sample_count,bounds):
    """Require two consecutive positive 32 ms chunks near the target syllable.

    Uses the usual 0.5 VAD cutoff and fixed 30 ms padding, not nasal labels or
    an optimized threshold on the background set. A miss becomes unknown.
    """
    p=np.asarray(scores)
    if p.ndim!=1 or len(p)!=(sample_count+511)//512 or not np.isfinite(p).all() or np.any((p<0)|(p>1)):
        raise ValueError('Invalid VAD time grid')
    begin,end=bounds['syllable']
    if not 0<=begin<end<=sample_count/16000+.01:
        raise ValueError('Invalid VAD target interval')
    starts=np.arange(len(p))*512/16000;ends=np.minimum(starts+512/16000,sample_count/16000)
    selected=(ends>max(0,begin-.03)) & (starts<end+.03) & (p>=.5)
    return bool(np.any(selected[1:] & selected[:-1]))


class SileroGate:
    def __init__(self):
        import onnxruntime as ort
        source=json.loads((FOLDER/'source.json').read_text())
        if source['revision']!=REVISION or any(sha(FOLDER/p)!=v for p,v in source['files'].items()):
            raise ValueError('Pinned VAD source changed')
        options=ort.SessionOptions();options.inter_op_num_threads=1;options.intra_op_num_threads=1
        self.session=ort.InferenceSession(str(FOLDER/'silero_vad.onnx'),options,providers=['CPUExecutionProvider'])
        if [r.name for r in self.session.get_inputs()]!=['input','state','sr']:
            raise ValueError('Unexpected ONNX VAD inputs')
        self.identity={'revision':REVISION,'model_sha256':source['files']['silero_vad.onnx'],
                       'onnxruntime':ort.__version__,'providers':self.session.get_providers(),
                       'sample_rate':16000,'chunk_samples':512,'context_samples':64}

    def score(self,samples):
        return probabilities(self.session,samples)


def parity():
    """Compare the reviewed official wrapper class; no remote module is executed."""
    import torch
    import warnings
    from nasal_acoustics import read_audio
    gate=SileroGate()
    module=ast.parse((FOLDER/'utils_vad.py').read_text())
    classes=[n for n in module.body if isinstance(n,ast.ClassDef) and n.name=='OnnxWrapper']
    if len(classes)!=1:
        raise ValueError('Reviewed upstream wrapper is missing')
    namespace={'torch':torch,'np':np,'warnings':warnings}
    exec(compile(ast.Module(body=classes,type_ignores=[]),'reviewed-OnnxWrapper','exec'),namespace)
    official=namespace['OnnxWrapper'](str(FOLDER/'silero_vad.onnx'),force_onnx_cpu=True)
    samples=read_audio(Path('data/derived/nasal-validation-v2/t1-05280.wav'))
    reports=[]
    for name,x in [('speech',samples),('silence_after_speech',np.zeros(12800,dtype=np.float32)),('speech_again',samples)]:
        ours=gate.score(x);theirs=official.audio_forward(torch.from_numpy(x.copy()),16000).numpy().reshape(-1)
        difference=float(np.max(np.abs(ours-theirs)))
        if difference>1e-6:
            raise RuntimeError('VAD implementation differs from official wrapper')
        reports.append({'input':name,'frames':len(ours),'maximum_difference':difference,
                        'target_speech':target_speech(ours,len(x),{'syllable':[0.,len(x)/16000]})})
    save_json(FOLDER/'parity.json',{'model':gate.identity,'checks':reports,'official_class_only':True})
    print(json.dumps(reports),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['fetch','parity']);args=parser.parse_args()
    {'fetch':fetch,'parity':parity}[args.mode]()
