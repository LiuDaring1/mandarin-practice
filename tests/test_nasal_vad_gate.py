from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from silero_nasal_gate import probabilities,target_speech


class FakeSession:
    def __init__(self):self.calls=[]
    def run(self,_,inputs):
        self.calls.append({k:v.copy() for k,v in inputs.items()})
        return np.array([[.75]],dtype=np.float32),inputs['state']+1


def test_stream_protocol_carries_context_pads_last_chunk_and_resets_recordings():
    session=FakeSession();samples=np.arange(600,dtype=np.float32)/1000
    assert probabilities(session,samples).shape==(2,)
    assert session.calls[0]['input'].shape==(1,576)
    assert np.all(session.calls[0]['input'][0,:64]==0)
    assert np.array_equal(session.calls[1]['input'][0,:64],samples[448:512])
    assert np.all(session.calls[1]['input'][0,64+88:]==0)
    assert np.all(session.calls[1]['state']==1)
    probabilities(session,np.zeros(512))
    assert np.all(session.calls[-1]['state']==0) and np.all(session.calls[-1]['input']==0)


def test_speech_elsewhere_does_not_admit_a_silent_target():
    scores=np.r_[np.ones(4),np.zeros(12)]
    assert target_speech(scores,8192,{'syllable':[0.,.1]})
    assert not target_speech(scores,8192,{'syllable':[.3,.5]})


def test_one_positive_spike_is_not_sustained_speech():
    assert not target_speech([0,.9,0,0],2048,{'syllable':[0,.128]})
    assert target_speech([0,.9,.8,0],2048,{'syllable':[0,.128]})


@pytest.mark.parametrize('scores',[[.9],[.9,float('nan')],[-.1,.9]])
def test_invalid_vad_grid_fails_closed(scores):
    with pytest.raises(ValueError):target_speech(scores,1024,{'syllable':[0,.064]})


def test_reused_fitting_engine_restores_its_original_root_after_failure():
    import probe_nasal_vad_fusion as experiment
    original=experiment.engine.FOLDER
    with pytest.raises(RuntimeError):
        with experiment.fitting_root():
            assert experiment.engine.FOLDER==experiment.FOLDER
            raise RuntimeError('interrupted experiment')
    assert experiment.engine.FOLDER==original
