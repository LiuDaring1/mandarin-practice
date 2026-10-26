"""Restrict only Xeus encoder context, retaining the original frontend output.

Waveform normalization, CNN features and preencoder projection are calculated
on the unchanged parent window. Local inference crops their frame sequence;
there is no second normalization, waveform cut, resampling or reference input.
"""
import numpy as np


def frame_times(frame_count, window_start=0, frame_start=0, stride=320, field=400):
    if frame_count<1 or window_start<0 or frame_start<0 or stride<=0 or field<=0:
        raise ValueError('Invalid encoder frame geometry')
    # Parent-relative times preserve the exact arithmetic of pool_regions.
    return ((np.arange(frame_count)+frame_start)*stride+field/2)/16000


def context_frames(bounds, window, frame_count, margin_ms, stride=320, field=400):
    a,b=window
    if not 0<=a<b or frame_count!=(b-a-field)//stride+1:
        raise ValueError('Parent frame grid differs from waveform')
    relative={key:[t-a/16000 for t in bounds[key]] for key in ('syllable','vowel')}
    left,right=relative['syllable'];begin,end=relative['vowel']
    if not np.isfinite([left,right,begin,end]).all() or not 0<=left<=begin<end<=right<=(b-a)/16000+.01:
        raise ValueError('Target outside parent window')
    if margin_ms is None: return 0,frame_count
    if not np.isfinite(margin_ms) or margin_ms<0: raise ValueError('Invalid encoder context margin')
    times=frame_times(frame_count,a,stride=stride,field=field)
    start=int(np.searchsorted(times,left-margin_ms/1000,side='left'))
    stop=int(np.searchsorted(times,right+margin_ms/1000,side='left'))
    if start>=stop: raise ValueError('Empty encoder context')
    return start,stop


def pool_trajectory(states,bounds,window_start,frame_start=0,stride=320,field=400):
    values=np.asarray(states)
    if values.ndim!=2 or not np.isfinite(values).all(): raise ValueError('Invalid local encoder states')
    begin,end=[t-window_start/16000 for t in bounds['vowel']]
    if not np.isfinite([begin,end]).all() or not 0<=begin<end: raise ValueError('Invalid vowel interval')
    times=frame_times(len(values),window_start,frame_start,stride,field)
    midpoint=(begin+end)/2;pooled=[]
    for left,right in [(begin,midpoint),(midpoint,end)]:
        selected=values[(times>=left)&(times<right)]
        if not len(selected): raise ValueError('Empty local target half')
        pooled.append(selected.mean(axis=0))
    return np.stack(pooled).reshape(-1)


def preprocess(wrapper,samples):
    import torch
    samples=np.asarray(samples,dtype=np.float32)
    if samples.ndim!=1 or not 1600<=len(samples)<=320000 or not np.isfinite(samples).all():
        raise ValueError('Expected finite parent waveform within 0.1–20 seconds')
    model=wrapper.model
    if model.training or model.weighted_sum or model.interctc_ctc_type=='ortho':
        raise ValueError('Unsupported original Xeus inference path')
    speech=torch.from_numpy(samples.copy()).unsqueeze(0).to(wrapper.device)
    lengths=torch.tensor([len(samples)],dtype=torch.long,device=wrapper.device)
    with torch.inference_mode(): features,feature_lengths=model._apply_preprocessing(speech,lengths)
    expected=(len(samples)-wrapper.field)//wrapper.stride+1
    if (features.ndim!=3 or features.shape[0]!=1 or features.shape[1]!=expected
            or int(feature_lengths[0])!=expected or not torch.isfinite(features).all()):
        raise ValueError('Preprocessing changed the parent frame grid')
    return features


def encode_frames(wrapper,features):
    import torch
    if features.ndim!=3 or features.shape[0]!=1 or features.shape[1]<1:
        raise ValueError('Expected one finite frame sequence')
    count=features.shape[1]
    lengths=torch.tensor([count],dtype=torch.long,device=features.device)
    masks=torch.zeros((1,count),dtype=torch.bool,device=features.device)
    wrapper.conditioning_calls=0;wrapper.conditioning_norms=[]
    with torch.inference_mode():
        encoded,output_lengths,_=wrapper.model.encoder(features.clone(),lengths,masks=masks,ctc=wrapper.model.ctc)
        final,intermediate=encoded;states=final[0].float().cpu().numpy().copy()
    if (int(output_lengths[0])!=count or len(states)!=count or not np.isfinite(states).all()
            or [i for i,_ in intermediate]!=[4,8,12] or wrapper.conditioning_calls!=3
            or not all(np.isfinite(v) and v>0 for v in wrapper.conditioning_norms)):
        raise ValueError('Local inference changed Xeus grid or conditioning path')
    return states
