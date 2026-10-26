"""Label-free short-time spectral/formant trajectories, for offline research.

Frame centres are measured, not assumed to delimit the phonetic segment.
Missing formants stay NaN until training-only imputation. Neither reference
spelling, speaker identity, API scores nor actual labels enter extraction.
"""
import numpy as np

from nasal_feature_probe import LABELS, predict_ridge

PARAMETERS = {
    'sample_rate':16000, 'frame_samples':400, 'hop_samples':80, 'fft_samples':512,
    'mel_filters':26, 'mel_low_hz':50., 'mel_high_hz':7600., 'preemphasis':.97,
    'cepstral_indices':list(range(1,13)), 'delta_radius':2, 'vowel_parts':3,
    'time_tolerance_seconds':1e-10,
    'formant_ceilings_hz':[5000.,5500.], 'formant_count':5.,
    'formant_effective_window_seconds':.025, 'formant_step_seconds':.005,
    'formant_preemphasis_from_hz':50., 'formants_kept':[1,2,3],
}
VIEWS = ('xeus','mfcc','mfcc_cmn','mfcc_formant','mfcc_cmn_formant',
         'xeus_mfcc_formant','xeus_mfcc_cmn_formant')


def waveform(samples):
    x=np.asarray(samples,dtype=np.float64)
    if x.ndim!=1 or not 1600<=len(x)<=320000 or not np.isfinite(x).all():
        raise ValueError('Expected a finite mono parent window of 0.1–20 seconds')
    x=x-x.mean();peak=np.max(np.abs(x))
    return x/peak if peak>0 else np.zeros_like(x)


def mel_bank():
    p=PARAMETERS
    mel=lambda f:2595*np.log10(1+np.asarray(f)/700)
    hz=lambda m:700*(10**(np.asarray(m)/2595)-1)
    edges=hz(np.linspace(mel(p['mel_low_hz']),mel(p['mel_high_hz']),p['mel_filters']+2))
    frequencies=np.fft.rfftfreq(p['fft_samples'],1/p['sample_rate'])
    bank=np.maximum(0,np.minimum((frequencies[None]-edges[:-2,None])/(edges[1:-1]-edges[:-2])[:,None],
                                (edges[2:,None]-frequencies[None])/(edges[2:]-edges[1:-1])[:,None]))
    if not (bank.sum(axis=1)>0).all(): raise ValueError('Empty mel filter')
    return bank/bank.sum(axis=1,keepdims=True)


def delta(values):
    x=np.asarray(values,dtype=np.float64)
    if x.ndim!=2 or not len(x) or not np.isfinite(x).all(): raise ValueError('Invalid delta sequence')
    radius=PARAMETERS['delta_radius'];padded=np.pad(x,((radius,radius),(0,0)),mode='edge')
    return sum(n*(padded[radius+n:radius+n+len(x)]-padded[radius-n:radius-n+len(x)])
               for n in range(1,radius+1))/(2*sum(n*n for n in range(1,radius+1)))


def spectral_frames(samples):
    p=PARAMETERS;x=waveform(samples)
    emphasized=np.r_[x[0],x[1:]-p['preemphasis']*x[:-1]]
    frames=np.lib.stride_tricks.sliding_window_view(emphasized,p['frame_samples'])[::p['hop_samples']]
    power=np.abs(np.fft.rfft(frames*np.hamming(p['frame_samples']),n=p['fft_samples'],axis=1))**2
    logmel=np.log(np.maximum(power@mel_bank().T,1e-12))
    frequencies=np.asarray(p['cepstral_indices'])[:,None]
    basis=np.sqrt(2/p['mel_filters'])*np.cos(np.pi*frequencies*(np.arange(p['mel_filters'])+.5)/p['mel_filters'])
    cepstra=logmel@basis.T;velocity=delta(cepstra);acceleration=delta(velocity)
    raw=np.concatenate([cepstra,velocity,acceleration],axis=1)
    cmn=np.concatenate([cepstra-cepstra.mean(axis=0),velocity,acceleration],axis=1)
    times=(np.arange(len(frames))*p['hop_samples']+p['frame_samples']/2)/p['sample_rate']
    return times,raw,cmn


def regions(bounds,window_start):
    left,right=np.asarray(bounds['vowel'],dtype=float)-window_start/16000
    if not np.isfinite([left,right]).all() or not 0<=left<right: raise ValueError('Invalid vowel interval')
    return np.linspace(left,right,PARAMETERS['vowel_parts']+1)


def interval_mask(times,left,right):
    # Subtracting a parent offset can move an exact decimal boundary by a few
    # ulps. Keep the intended [left,right) membership stable at that boundary.
    tolerance=PARAMETERS['time_tolerance_seconds']
    return (times>=left-tolerance)&(times<right-tolerance)


def pool_spectrum(times,values,bounds,window_start=0):
    t=np.asarray(times);x=np.asarray(values)
    if t.ndim!=1 or x.ndim!=2 or len(t)!=len(x) or not np.isfinite(x).all(): raise ValueError('Invalid spectral frames')
    edges=regions(bounds,window_start);result=[]
    for left,right in zip(edges[:-1],edges[1:]):
        chosen=x[interval_mask(t,left,right)]
        if not len(chosen): raise ValueError('Empty spectral third; do not borrow adjacent speech')
        result.append(chosen.mean(axis=0))
    return np.concatenate(result)


def formant_frames(samples):
    import parselmouth
    p=PARAMETERS;sound=parselmouth.Sound(waveform(samples),sampling_frequency=16000)
    result=[]
    for ceiling in p['formant_ceilings_hz']:
        formants=sound.to_formant_burg(time_step=p['formant_step_seconds'],max_number_of_formants=p['formant_count'],
            maximum_formant=ceiling,window_length=p['formant_effective_window_seconds'],
            pre_emphasis_from=p['formant_preemphasis_from_hz'])
        times=np.asarray(formants.xs())
        frequency=np.array([[formants.get_value_at_time(k,float(t)) for k in p['formants_kept']] for t in times])
        bandwidth=np.array([[formants.get_bandwidth_at_time(k,float(t)) for k in p['formants_kept']] for t in times])
        valid=np.isfinite(frequency)&np.isfinite(bandwidth)&(frequency>=50)&(frequency<=ceiling-50)&(bandwidth>0)
        values=np.full((len(times),6),np.nan)
        values[:,:3][valid]=np.log(frequency[valid]);values[:,3:][valid]=np.log(bandwidth[valid])
        result.append((times,values))
    return result


def pool_formants(contours,bounds,window_start=0):
    result=[];edges=regions(bounds,window_start)
    for times,values in contours:
        x=np.asarray(values);t=np.asarray(times)
        if x.shape!=(len(t),6) or np.isinf(x).any(): raise ValueError('Invalid formant contours')
        for left,right in zip(edges[:-1],edges[1:]):
            chosen=x[interval_mask(t,left,right)]
            medians=[float(np.median(v[np.isfinite(v)])) if np.isfinite(v).any() else np.nan for v in chosen.T]
            missing=1-np.isfinite(chosen[:,:3]).mean(axis=0) if len(chosen) else np.ones(3)
            result.extend(medians);result.extend(missing)
    return np.asarray(result)


def feature_view(xeus,mfcc,cmn,formants,view):
    if view not in VIEWS: raise ValueError('Unknown direct acoustic view')
    arrays=[]
    if 'xeus' in view: arrays.append(np.asarray(xeus))
    if 'mfcc' in view: arrays.append(np.asarray(cmn if 'cmn' in view else mfcc))
    if 'formant' in view: arrays.append(np.asarray(formants))
    if any(x.ndim!=2 or len(x)!=len(arrays[0]) or np.isinf(x).any() for x in arrays): raise ValueError('Invalid acoustic feature blocks')
    return np.concatenate(arrays,axis=1),[x.shape[1] for x in arrays]


def fit_blocks(features,labels,regularization,blocks):
    x=np.asarray(features,dtype=np.float64);y=np.asarray(labels,dtype=np.int64)
    if x.ndim!=2 or not len(x) or len(x)!=len(y) or np.isinf(x).any(): raise ValueError('Invalid training features')
    if not blocks or any(not isinstance(n,int) or n<1 for n in blocks) or sum(blocks)!=x.shape[1]: raise ValueError('Invalid block dimensions')
    if set(y.tolist())!=set(range(len(LABELS))) or not np.isfinite(regularization) or regularization<=0: raise ValueError('Need all classes and positive regularization')
    impute=np.array([np.median(v[np.isfinite(v)]) if np.isfinite(v).any() else 0. for v in x.T])
    x=np.where(np.isnan(x),impute,x)
    counts=np.bincount(y,minlength=len(LABELS));weight=len(y)/(len(LABELS)*counts[y])
    mean=np.average(x,axis=0,weights=weight)
    scale=np.maximum(np.sqrt(np.average((x-mean)**2,axis=0,weights=weight)),1e-4)
    # Equal aggregate weight per named block, instead of letting 2048 Xeus
    # coordinates drown out 108 spectral and 54 formant coordinates.
    scale*=np.concatenate([np.full(n,np.sqrt(n*len(blocks)/x.shape[1])) for n in blocks])
    z=(x-mean)/scale/np.sqrt(x.shape[1]);target=np.eye(len(LABELS))[y]
    intercept=np.average(target,axis=0,weights=weight);root=np.sqrt(weight)[:,None];a=z*root
    dual=np.linalg.solve(a@a.T+regularization*np.eye(len(x)),(target-intercept)*root)
    return {'mean':mean,'scale':scale,'coefficient':a.T@dual,'intercept':intercept,'impute':impute}


def predict_blocks(model,features):
    x=np.asarray(features,dtype=np.float64)
    if x.ndim!=2 or x.shape[1]!=len(model['impute']) or np.isinf(x).any(): raise ValueError('Invalid prediction features')
    return predict_ridge(model,np.where(np.isnan(x),model['impute'],x))
