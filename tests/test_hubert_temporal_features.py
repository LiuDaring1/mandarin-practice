from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from chinese_hubert_features import pool_halves
from hubert_temporal_features import VIEWS,pool_views


@pytest.mark.parametrize('offset',[0,256000,291487])
def test_parent_offsets_preserve_baseline_and_half_open_frame_selection(offset):
    x=np.arange(49,dtype=np.float32)[:,None]
    bounds={'syllable':[offset/16000,offset/16000+.3],'vowel':[offset/16000+.0125,offset/16000+.2125]}
    result,count=pool_views(x,bounds,offset,16000)
    assert count==10 and set(result)==set(VIEWS)
    np.testing.assert_array_equal(result['trajectory2'],[2.,7.])
    np.testing.assert_array_equal(result['trajectory2'],pool_halves(x[None],bounds,offset,16000)[0])
    changed=x.copy();changed[10:]=1000000
    other,other_count=pool_views(changed,bounds,offset,16000)
    assert other_count==count
    for view in VIEWS:np.testing.assert_array_equal(result[view],other[view])


def test_time_detail_separates_sequences_with_identical_half_means():
    x=np.zeros((49,1),dtype=np.float32);x[:4,0]=[0,2,2,0]
    y=x.copy();y[:4,0]=1
    bounds={'syllable':[0,.1],'vowel':[.0025,.0825]}
    left,count=pool_views(x,bounds,0,16000);right,_=pool_views(y,bounds,0,16000)
    assert count==4
    np.testing.assert_array_equal(left['trajectory2'],right['trajectory2'])
    np.testing.assert_allclose(left['resampled4'],[0,2,2,0],atol=1e-6)
    assert not np.allclose(left['resampled4'],right['resampled4'])


def test_absolute_tail_windows_and_tail_change_match_known_sequence():
    x=np.arange(49,dtype=np.float32)[:,None]
    result,count=pool_views(x,{'syllable':[0,.3],'vowel':[.0025,.2025]},0,16000)
    assert count==10
    np.testing.assert_allclose(result['tail_stats'],[4.5,6.5,8.,7.])


def test_two_observed_frames_remain_two_observations_after_resampling():
    x=np.zeros((49,1),dtype=np.float32);x[:2,0]=[1,3]
    result,count=pool_views(x,{'syllable':[0,.1],'vowel':[.0025,.0425]},0,16000)
    assert count==2 and result['resampled8'].shape==(8,)
    np.testing.assert_allclose(result['resampled4'],[1,1.5,2.5,3])
    assert result['resampled8'].min()==1 and result['resampled8'].max()==3


def test_reversing_observed_time_changes_temporal_order():
    x=np.arange(49,dtype=np.float32)[:,None];y=x.copy();y[:4]=x[:4][::-1]
    bounds={'syllable':[0,.1],'vowel':[.0025,.0825]}
    left,_=pool_views(x,bounds,0,16000);right,_=pool_views(y,bounds,0,16000)
    np.testing.assert_allclose(left['resampled8'],right['resampled8'][::-1],atol=1e-6)


@pytest.mark.parametrize('x', [np.ones((48,2)),np.full((49,2),np.nan),np.ones((4,49,2))])
def test_wrong_grid_nonfinite_or_multiple_layers_are_rejected(x):
    with pytest.raises(ValueError):pool_views(x,{'syllable':[0,.3],'vowel':[.1,.2]},0,16000)


@pytest.mark.parametrize('bounds',[
    {'syllable':[0,1.1],'vowel':[.1,.2]},
    {'syllable':[0,.5],'vowel':[.499,.5]},
    {'syllable':[0,.3],'vowel':[.2,.1]},
])
def test_invalid_or_unobserved_target_is_not_filled_from_neighbor(bounds):
    with pytest.raises(ValueError):pool_views(np.ones((49,2)),bounds,0,16000)
