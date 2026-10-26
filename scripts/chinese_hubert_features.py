"""Frozen Mandarin HuBERT audio representations; no text or labels at inference."""
import hashlib
import json
from pathlib import Path

import numpy as np

from fetch_chinese_hubert import FOLDER, REPOSITORY, REVISION

LAYERS = (6, 12, 18, 24)
VIEWS = ('xeus',) + tuple(f'hubert_{layer}' for layer in LAYERS)


def geometry(kernels, strides):
    if not kernels or len(kernels) != len(strides) or any(type(x) is not int or x <= 0 for x in list(kernels)+list(strides)):
        raise ValueError('Invalid convolution geometry')
    step, field = 1, 1
    for kernel, stride in zip(kernels, strides):
        field += (kernel-1)*step
        step *= stride
    return step, field


def pool_halves(states, bounds, start_sample, sample_count, stride=320, field=400):
    values = np.asarray(states)
    if (type(start_sample) is not int or start_sample < 0 or type(sample_count) is not int or
            stride <= 0 or field <= 0 or values.ndim != 3 or not np.isfinite(values).all() or
            values.shape[1] != (sample_count-field)//stride+1 or values.shape[1] <= 0):
        raise ValueError('Invalid hidden state grid')
    left, right = bounds['syllable']; begin, end = bounds['vowel']
    offset = start_sample/16000
    if not np.isfinite([left,right,begin,end]).all() or not offset <= left <= begin < end <= right <= offset+sample_count/16000+1e-10:
        raise ValueError('Target outside parent window')
    times = (np.arange(values.shape[1])*stride+field/2)/16000
    a, b = begin-offset, end-offset; middle = (a+b)/2
    result = []
    for lo, hi in ((a,middle),(middle,b)):
        mask = (times >= lo-1e-10) & (times < hi-1e-10)
        if not mask.any(): raise ValueError('Empty target half; no adjacent speech fallback')
        result.append(values[:,mask].mean(axis=1))
    return np.stack(result,axis=1).reshape(len(values),-1)


def feature_view(baseline, features, view):
    if view not in VIEWS: raise ValueError('Unregistered feature view')
    if view == 'xeus': return baseline
    return features[:, LAYERS.index(int(view.split('_')[1]))]


class ChineseHubert:
    def __init__(self, device='cpu'):
        import torch
        import transformers
        from transformers import HubertModel, Wav2Vec2FeatureExtractor
        if device != 'cpu': raise ValueError('This experiment requires CPU after failed MPS parity preflight')
        torch.set_num_threads(4)
        source = json.loads((FOLDER/'source.json').read_text())
        if source['repository'] != REPOSITORY or source['revision'] != REVISION:
            raise ValueError('Unexpected model identity')
        for path, spec in source['sources'].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != spec['sha256']:
                raise ValueError('Model source changed')
        self.extractor = Wav2Vec2FeatureExtractor.from_pretrained(FOLDER, local_files_only=True)
        if self.extractor.sampling_rate != 16000 or not self.extractor.do_normalize:
            raise ValueError('Unexpected audio preprocessing')
        self.model, info = HubertModel.from_pretrained(FOLDER, local_files_only=True, use_safetensors=False,
            weights_only=True, output_loading_info=True, attn_implementation='eager')
        if any(info.get(key) for key in ('missing_keys','unexpected_keys','mismatched_keys','error_msgs')):
            raise ValueError('Incomplete checkpoint loading: '+str(info))
        self.stride, self.field = geometry(self.model.config.conv_kernel,self.model.config.conv_stride)
        if (self.stride,self.field,self.model.config.num_hidden_layers,self.model.config.hidden_size) != (320,400,24,1024):
            raise ValueError('Unexpected model/grid')
        self.model.eval().requires_grad_(False).to(device=device,dtype=torch.float32)
        self.device = device
        self.identity = {'repository': REPOSITORY,'revision': REVISION,'source_sha256': hashlib.sha256((FOLDER/'source.json').read_bytes()).hexdigest(),
            'torch':torch.__version__,'transformers':transformers.__version__,'device':device,'dtype':'float32',
            'attention':'eager','cpu_threads':4,'remote_code':False,'weights_only':True,'layers':list(LAYERS),'stride':self.stride,'field':self.field}

    def infer(self, samples):
        import torch
        audio = np.asarray(samples,dtype=np.float32)
        if audio.ndim != 1 or not 1600 <= len(audio) <= 320000 or not np.isfinite(audio).all():
            raise ValueError('Invalid 0.1–20 second mono waveform')
        inputs = self.extractor(audio,sampling_rate=16000,return_tensors='pt',padding=False)
        inputs = {key:value.to(self.device) for key,value in inputs.items()}
        with torch.inference_mode(): output = self.model(**inputs,output_hidden_states=True)
        count = (len(audio)-self.field)//self.stride+1
        if len(output.hidden_states) != 25 or tuple(output.last_hidden_state.shape) != (1,count,1024):
            raise ValueError('Actual inference disagrees with nominal grid')
        if not torch.equal(output.hidden_states[-1],output.last_hidden_state):
            raise ValueError('Layer numbering mismatch')
        selected = np.stack([output.hidden_states[i][0].float().cpu().numpy() for i in LAYERS])
        if not np.isfinite(selected).all(): raise ValueError('Nonfinite model output')
        return selected
