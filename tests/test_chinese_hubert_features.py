from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from chinese_hubert_features import geometry,pool_halves,feature_view,LAYERS
from probe_chinese_hubert import rank


def test_convolution_grid_independent_length_recurrence():
    kernels=[10,3,3,3,3,2,2];strides=[5,2,2,2,2,2,2]
    step,field=geometry(kernels,strides)
    assert (step,field)==(320,400)
    for count in (1600,16000,19017,320000):
        remaining=count
        for k,s in zip(kernels,strides): remaining=(remaining-k)//s+1
        assert remaining==(count-field)//step+1


@pytest.mark.parametrize('kernels,strides',[([],[]),([2],[1,2]),([0],[2]),([2],[-1]),([2.5],[1])])
def test_invalid_convolution_spec(kernels,strides):
    with pytest.raises(ValueError,match='geometry'): geometry(kernels,strides)


@pytest.mark.parametrize('offset',[0,256000,291487])
def test_parent_offset_and_half_open_boundary_do_not_include_next_frame(offset):
    # Frame centers .0125,.0325,...; end exactly .2125 must exclude frame 10.
    states=np.arange(49,dtype=np.float32)[None,:,None]+np.arange(4)[:,None,None]*100
    bounds={'syllable':[offset/16000,offset/16000+.3],
            'vowel':[offset/16000+.0125,offset/16000+.2125]}
    result=pool_halves(states,bounds,offset,16000)
    expected=np.array([[states[layer,:5,0].mean(),states[layer,5:10,0].mean()] for layer in range(4)])
    np.testing.assert_array_equal(result,expected)


def test_empty_target_half_never_uses_adjacent_speech():
    with pytest.raises(ValueError,match='Empty target half'):
        pool_halves(np.ones((4,49,3)),{'syllable':[.5,.55],'vowel':[.51,.511]},0,16000)


@pytest.mark.parametrize('bounds',[
    {'syllable':[0,1.1],'vowel':[.8,.9]},
    {'syllable':[0,.5],'vowel':[.4,.6]},
    {'syllable':[0,.5],'vowel':[.4,.4]},
    {'syllable':[0,.5],'vowel':[np.nan,.4]},
])
def test_invalid_target_envelope(bounds):
    with pytest.raises(ValueError,match='outside'): pool_halves(np.ones((4,49,3)),bounds,0,16000)


def test_wrong_frame_count_and_nonfinite_states_rejected():
    bounds={'syllable':[0,.5],'vowel':[.1,.4]}
    for values in [np.ones((4,48,3)),np.full((4,49,3),np.nan),np.ones((49,3))]:
        with pytest.raises(ValueError,match='grid'): pool_halves(values,bounds,0,16000)


def test_layer_lookup_and_baseline_are_not_selected_by_label():
    baseline=np.arange(18).reshape(3,6)
    features=np.arange(72).reshape(3,4,6)
    assert feature_view(baseline,features,'xeus') is baseline
    for i,layer in enumerate(LAYERS):
        np.testing.assert_array_equal(feature_view(baseline,features,f'hubert_{layer}'),features[:,i])
    with pytest.raises(ValueError,match='Unregistered'): feature_view(baseline,features,'hubert_7')


def test_tied_development_prefers_original_model_then_stronger_regularization():
    base={'development':{'correct_error_directions':20,'correct_nasal_matches':90},'view':'xeus','regularization':.01}
    candidate={**base,'view':'hubert_12','regularization':1.}
    assert rank(base)<rank(candidate)
    assert rank({**candidate,'regularization':1.})<rank({**candidate,'regularization':.1})


def test_model_selection_requires_better_development_evidence():
    base={'development':{'correct_error_directions':20,'correct_nasal_matches':90},'view':'xeus','regularization':.1}
    candidate={**base,'view':'hubert_12','development':{'correct_error_directions':21,'correct_nasal_matches':88}}
    assert rank(candidate)<rank(base)
