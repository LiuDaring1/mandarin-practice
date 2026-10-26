from pathlib import Path
import sys

import numpy as np
import pytest
from scipy.fft import dct

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from nasal_direct_acoustics import (PARAMETERS,delta,feature_view,fit_blocks,mel_bank,
    pool_formants,pool_spectrum,predict_blocks,spectral_frames,waveform)
from nasal_feature_probe import fit_ridge,predict_ridge


def tone():
    t=np.arange(16000)/16000
    return np.sin(2*np.pi*220*t)+.4*np.sin(2*np.pi*1300*t)+.2*np.sin(2*np.pi*2400*t)


def test_mfcc_matches_independent_scipy_dct_and_frame_grid():
    x=waveform(tone());emphasis=np.r_[x[0],x[1:]-.97*x[:-1]]
    frames=np.stack([emphasis[i:i+400] for i in range(0,len(x)-399,80)])
    power=np.abs(np.fft.rfft(frames*np.hamming(400),n=512,axis=1))**2
    expected=dct(np.log(np.maximum(power@mel_bank().T,1e-12)),type=2,norm='ortho',axis=1)[:,1:13]
    times,raw,cmn=spectral_frames(tone())
    np.testing.assert_allclose(raw[:,:12],expected,atol=1e-12)
    np.testing.assert_array_equal(times,(np.arange(len(frames))*80+200)/16000)
    np.testing.assert_allclose(cmn[:,:12].mean(axis=0),0,atol=1e-12)
    np.testing.assert_array_equal(raw[:,12:],cmn[:,12:])


@pytest.mark.parametrize('gain',[.0001,.2,-1.,10.])
def test_spectral_features_are_gain_and_polarity_invariant(gain):
    reference=spectral_frames(tone())[1]
    np.testing.assert_allclose(spectral_frames(gain*tone())[1],reference,atol=1e-9)


def test_delta_constant_and_ramp():
    np.testing.assert_array_equal(delta(np.ones((10,4))),np.zeros((10,4)))
    np.testing.assert_array_equal(delta(np.arange(20)[:,None])[2:-2],np.ones((16,1)))


def test_silence_is_finite_but_not_claimed_as_speech():
    _,raw,cmn=spectral_frames(np.zeros(16000))
    assert np.isfinite(raw).all() and np.isfinite(cmn).all()
    np.testing.assert_allclose(raw,0,atol=1e-12)


@pytest.mark.parametrize('bad',[np.ones((1600,1)),np.zeros(399),np.full(1600,np.nan)])
def test_bad_waveforms_rejected(bad):
    with pytest.raises(ValueError,match='parent window'):spectral_frames(bad)


def test_regions_do_not_pool_neighboring_speech_and_keep_global_offset():
    times=np.arange(100)/100;values=np.where((times>=.3)&(times<.6),2.,1000.)[:,None]
    expected=np.array([2.,2.,2.])
    np.testing.assert_array_equal(pool_spectrum(times,values,{'vowel':[.3,.6]}),expected)
    np.testing.assert_array_equal(pool_spectrum(times,values,{'vowel':[2.3,2.6]},32000),expected)


def test_empty_region_refuses_neighbor_fallback():
    with pytest.raises(ValueError,match='Empty spectral third'):
        pool_spectrum(np.array([.15]),np.ones((1,4)),{'vowel':[.1,.4]})


def test_missing_formants_remain_missing_with_explicit_fraction():
    times=np.array([.1,.2,.3]);values=np.tile(np.log([500,1500,2500,80,100,150]),(3,1))
    values[1,[1,4]]=np.nan
    pooled=pool_formants([(times,values),(times,values)],{'vowel':[.05,.35]})
    assert pooled.shape==(54,)
    assert np.isnan(pooled[10]) and np.isnan(pooled[13])
    np.testing.assert_array_equal(pooled[15:18],[0,1,0])
    np.testing.assert_array_equal(pooled[:9],pooled[27:36])


def test_formant_region_without_frames_not_fabricated():
    pooled=pool_formants([(np.array([.3]),np.ones((1,6)))],{'vowel':[.1,.4]})
    assert np.isnan(pooled[:6]).all()
    np.testing.assert_array_equal(pooled[6:9],np.ones(3))


def training():
    x=np.random.default_rng(72).normal(size=(18,7));y=np.arange(18)%3
    return x,y


def test_single_block_exactly_replays_original_ridge():
    x,y=training();a=fit_blocks(x,y,.1,[7]);b=fit_ridge(x,y,.1)
    for key in b:np.testing.assert_array_equal(a[key],b[key])
    np.testing.assert_array_equal(predict_blocks(a,x),predict_ridge(b,x))


def test_missing_imputation_uses_training_only_and_survives_save(tmp_path):
    x,y=training();x[0,0]=np.nan;x[:,1]=np.nan
    model=fit_blocks(x,y,.1,[3,4])
    assert model['impute'][0]==np.median(x[1:,0]) and model['impute'][1]==0
    query=x[:2].copy();query[:,0]=np.nan
    manual=np.where(np.isnan(query),model['impute'],query)
    expected=predict_ridge(model,manual)
    np.testing.assert_array_equal(predict_blocks(model,query),expected)
    path=tmp_path/'model.npz';np.savez_compressed(path,**model)
    with np.load(path,allow_pickle=False) as stored:
        np.testing.assert_array_equal(predict_blocks(dict(stored),query),expected)


def test_each_standardized_block_has_equal_aggregate_training_energy():
    x,y=training();model=fit_blocks(x,y,.1,[2,5]);z=(x-model['mean'])/model['scale']/np.sqrt(7)
    np.testing.assert_allclose(np.mean((z[:,:2]**2).sum(axis=1)),.5)
    np.testing.assert_allclose(np.mean((z[:,2:]**2).sum(axis=1)),.5)


@pytest.mark.parametrize('blocks',[[3,3],[],[0,7],[2.5,4.5]])
def test_invalid_feature_blocks_rejected(blocks):
    x,y=training()
    with pytest.raises(ValueError,match='block'):fit_blocks(x,y,.1,blocks)


def test_feature_views_keep_distinct_blocks_and_missing_values():
    arrays=[np.full((4,d),i) for i,d in enumerate((2048,108,108,54))]
    arrays[-1]=arrays[-1].astype(float);arrays[-1][0,0]=np.nan
    x,blocks=feature_view(*arrays,'xeus_mfcc_cmn_formant')
    assert blocks==[2048,108,54] and x.shape==(4,2210)
    assert (x[:,2048:2156]==2).all() and np.isnan(x[0,2156])
    with pytest.raises(ValueError,match='Unknown'):feature_view(*arrays,'expected_ng')


def test_bad_labels_and_nonfinite_prediction_rejected():
    x,y=training()
    with pytest.raises(ValueError,match='classes'):fit_blocks(x,np.zeros(18),.1,[7])
    model=fit_blocks(x,y,.1,[7]);x[0,0]=np.inf
    with pytest.raises(ValueError,match='prediction'):predict_blocks(model,x)


def test_tied_development_preserves_baseline():
    from probe_direct_acoustics import rank
    c={'development':{'correct_error_directions':10,'correct_nasal_matches':90},'regularization':.1,'view':'xeus'}
    assert rank(c)<rank({**c,'view':'xeus_mfcc_formant'})
