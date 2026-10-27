"""Time-preserving views of observed Mandarin HuBERT vowel frames."""
import numpy as np

from chinese_hubert_features import pool_halves

VIEWS = ('trajectory2','resampled4','resampled8','tail_stats')
WIDTHS = {'trajectory2':2,'resampled4':4,'resampled8':8,'tail_stats':4}


def pool_views(states,bounds,start_sample,sample_count,stride=320,field=400):
    values = np.asarray(states)
    if values.ndim!=2:raise ValueError('Expected one hidden layer')
    baseline = pool_halves(values[None],bounds,start_sample,sample_count,stride,field)[0]
    offset = start_sample/16000
    begin,end = np.asarray(bounds['vowel'])-offset
    times = (np.arange(len(values))*stride+field/2)/16000
    mask = (times>=begin-1e-10)&(times<end-1e-10)
    observed = values[mask]; positions = times[mask]
    if len(observed)<2:raise ValueError('Insufficient observed vowel frames')
    result = {'trajectory2':baseline}
    for count in (4,8):
        queries = begin+(np.arange(count)+.5)/count*(end-begin)
        # Repeated endpoints interpolate existing observations; they never add
        # new acoustic frames or read a frame outside the annotated vowel.
        result[f'resampled{count}'] = np.stack([np.interp(queries,positions,c) for c in observed.T],axis=1).astype(np.float32).reshape(-1)
    def mean(left,right):
        chosen = observed[(positions>=left-1e-10)&(positions<right-1e-10)]
        if not len(chosen):raise ValueError('Empty observed temporal interval')
        return chosen.mean(axis=0)
    early = mean(begin,min(end,begin+.06));late = mean(max(begin,end-.06),end)
    result['tail_stats'] = np.stack([mean(begin,end),mean(max(begin,end-.12),end),late,late-early]).reshape(-1)
    return result,len(observed)
