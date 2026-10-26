"""Numerical/extraction checks before fitting any direct acoustic classifier."""
from pathlib import Path

import numpy as np
from scipy.signal import lfilter

from nasal_acoustics import read_audio
from nasal_direct_acoustics import spectral_frames,formant_frames,pool_spectrum,pool_formants
from extract_direct_acoustics import runtime
from probe_xeus_encoder_context import load_base,engine
from train_nasal_feature_probe import save_json
from zipa_context import context_interval


def main():
    import parselmouth
    folder=engine.BASE/'direct-acoustics-preflight-v1'
    if folder.exists(): raise ValueError('Direct preflight already saved')
    synthetic=[]
    for count in (3,5):
        x=np.random.default_rng(291).normal(size=32000)
        resonances=[(500,80),(1500,100),(2500,120),(3500,150),(4500,180)][:count]
        for frequency,bandwidth in resonances:
            r=np.exp(-np.pi*bandwidth/16000)
            x=lfilter([1],[1,-2*r*np.cos(2*np.pi*frequency/16000),r*r],x)
        measured=[]
        for t,v in formant_frames(x):
            median=np.exp(np.nanmedian(v[(t>.3)&(t<1.7),:3],axis=0))
            if not np.isfinite(median).all(): raise ValueError('Synthetic formant extraction nonfinite')
            measured.append(median.tolist())
        synthetic.append({'generating_resonances_hz':[f for f,_ in resonances],
            'estimated_first_three_by_ceiling':measured,
            'maximum_first_three_difference_hz':max(float(np.max(np.abs(np.array(v)-[500,1500,2500]))) for v in measured)})
    rows,_,_,_=load_base('existing');row=next(r for r in rows if r['split']=='train')
    samples=read_audio(Path(row['audio']),max_seconds=180);a,b=context_interval(len(samples),row['bounds']['syllable'])
    times,raw,cmn=spectral_frames(samples[a:b]);contours=formant_frames(samples[a:b])
    values=[pool_spectrum(times,raw,row['bounds'],a),pool_spectrum(times,cmn,row['bounds'],a),pool_formants(contours,row['bounds'],a)]
    if [len(v) for v in values]!=[108,108,54] or not np.isfinite(values[:2]).all() or np.isinf(values[2]).any():
        raise ValueError('Training-only extraction preflight failed')
    paths=[Path('scripts')/n for n in ('nasal_direct_acoustics.py','preflight_direct_acoustics.py','extract_direct_acoustics.py','nasal_acoustics.py','zipa_context.py')]
    paths.append(Path(parselmouth.__file__))
    folder.mkdir();save_json(folder/'report.json',{'complete':True,'sources':{str(p):engine.sha(p) for p in paths},
        'runtime':runtime(),'train_target_id':row['id'],'train_audio_sha256':engine.sha(row['audio']),
        'feature_dimensions':[len(v) for v in values],'formant_missing_coordinates':int(np.isnan(values[2]).sum()),
        'synthetic_resonance_checks':synthetic,'no_classifier_fit':True,'evaluation_targets_used':False,
        'limit':'Five-pole Burg can introduce extra poles for a three-resonance source; ordinal F3 is not guaranteed to be the third generating resonance.'})
    print('DIRECT PREFLIGHT COMPLETE',synthetic,flush=True)


if __name__=='__main__':main()
