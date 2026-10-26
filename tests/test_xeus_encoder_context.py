from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from nasal_feature_probe import pool_regions
from xeus_encoder_context import context_frames,frame_times,pool_trajectory


@pytest.mark.parametrize('offset',[0,256000,291487])
@pytest.mark.parametrize('margin',[None,150,450])
def test_local_pool_preserves_original_target_frames(offset,margin):
    count=160000;frames=(count-400)//320+1
    states=np.random.default_rng(41).normal(size=(frames,8)).astype(np.float32)
    relative={'syllable':[1.3,1.9],'vowel':[1.45,1.9]}
    bounds={key:[v+offset/16000 for v in vals] for key,vals in relative.items()}
    exact_relative={key:[v-offset/16000 for v in vals] for key,vals in bounds.items()}
    expected=pool_regions(states,exact_relative,sample_count=count)[2:4].reshape(-1)
    start,stop=context_frames(bounds,(offset,offset+count),frames,margin)
    np.testing.assert_array_equal(pool_trajectory(states[start:stop],bounds,offset,start),expected)
    if margin is None: assert (start,stop)==(0,frames)
    else: assert 0<start<stop<frames


def test_clip_edges_never_request_nonexistent_context():
    count=32000;frames=(count-400)//320+1
    assert context_frames({'syllable':[0.,.2],'vowel':[.02,.2]},(0,count),frames,450)[0]==0
    assert context_frames({'syllable':[1.7,2.],'vowel':[1.8,2.]},(0,count),frames,450)[1]==frames


@pytest.mark.parametrize('margin',[-1,float('nan'),float('inf')])
def test_invalid_margin_rejected(margin):
    with pytest.raises(ValueError,match='margin'):
        context_frames({'syllable':[.1,.5],'vowel':[.2,.5]},(0,16000),49,margin)


def test_wrong_grid_and_outside_target_rejected():
    bounds={'syllable':[.1,.5],'vowel':[.2,.5]}
    with pytest.raises(ValueError,match='grid'): context_frames(bounds,(0,16000),48,150)
    with pytest.raises(ValueError,match='outside'): context_frames(bounds,(16000,32000),49,150)
    with pytest.raises(ValueError,match='outside'):
        context_frames({'syllable':[.1,.5],'vowel':[.2,.6]},(0,16000),49,150)


def test_empty_half_is_not_replaced_by_adjacent_speech():
    with pytest.raises(ValueError,match='Empty local target half'):
        pool_trajectory(np.ones((3,4)),{'vowel':[.2,.5]},0)


def test_time_grid_retains_parent_frame_offset():
    parent=frame_times(1000,12345)
    np.testing.assert_array_equal(frame_times(20,12345,233),parent[233:253])


def test_tied_development_prefers_unchanged_context():
    from probe_xeus_encoder_context import rank
    base={'development':{'correct_error_directions':20,'correct_nasal_matches':90}}
    full={**base,'margin_ms':None,'regularization':.01}
    local={**base,'margin_ms':450,'regularization':1.}
    assert rank(full)<rank(local)


def test_local_context_is_chosen_only_when_development_improves():
    from probe_xeus_encoder_context import rank
    full={'development':{'correct_error_directions':20,'correct_nasal_matches':90},'margin_ms':None,'regularization':.1}
    local={**full,'margin_ms':150,'development':{'correct_error_directions':21,'correct_nasal_matches':88}}
    assert rank(local)<rank(full)
