from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from nasal_feature_probe import (assert_speaker_partition,fit_ridge,pool_regions,
                                 predict_ridge,select_on_development,acoustic_window)
from prepare_nasal_feature_data import speaker_split
from train_nasal_feature_probe import observe,select_margin,select_matching_margin,summarize


def test_pools_use_physical_time_and_preserve_last_half():
    hidden=np.arange(10.)[:,None]
    pooled=pool_regions(hidden,{'syllable':[0,.2],'vowel':[.04,.16]},sample_count=3280)
    assert pooled[:,0].tolist()==[4.5,4.5,3.,6.]
    with pytest.raises(ValueError,match='time axis'):
        pool_regions(hidden,{'syllable':[0,.2],'vowel':[.04,.16]},sample_count=400)


def test_long_utterance_windows_preserve_whole_target_and_short_audio_behavior():
    assert acoustic_window({'syllable':[39.9,40.3]},16000*50)==(0,16000*50)
    assert acoustic_window({'syllable':[44.8,45.2]},16000*100)==(16000*40,16000*85)
    for bounds in [[.1,.5],[39.9,40.4],[44.8,45.2],[63.2,63.8],[98.,99.9]]:
        start,end=acoustic_window({'syllable':bounds},16000*100)
        assert start/16000<=bounds[0]<bounds[1]<=end/16000
        assert end-start<=16000*45
        assert start%320==0
    with pytest.raises(ValueError,match='complete target'):
        acoustic_window({'syllable':[39.,86.]},16000*100)


def test_classifier_standardization_does_not_use_evaluation_batch():
    x=np.array([[-2.,-1.],[-3.,-2.],[2.,-1.],[3.,-2.],[0.,2.],[0.,3.]])
    y=np.repeat(np.arange(3),2)
    original=x.copy();model=fit_ridge(x,y,.01)
    assert predict_ridge(model,x).argmax(axis=1).tolist()==y.tolist()
    np.testing.assert_array_equal(x,original)
    single=predict_ridge(model,x[:1])[0]
    mixed=predict_ridge(model,np.vstack([x[:1],[10000.,-10000.]]))[0]
    np.testing.assert_allclose(single,mixed)


def test_test_and_transfer_rows_cannot_tune_selection():
    for split in ['test','transfer']:
        with pytest.raises(ValueError,match='cannot receive'):
            select_on_development(np.zeros((1,4,4,2)),[{'split':split}])
    with pytest.raises(ValueError,match='development data only'):
        select_margin([{'split':'test'}],np.zeros((1,3)))
    with pytest.raises(ValueError,match='development data only'):
        select_matching_margin([{'split':'transfer'}],np.zeros((1,3)))


def test_speaker_partition_is_stable_and_cross_split_identity_is_rejected():
    assert speaker_split('eduhk:10')==speaker_split('eduhk:10')
    with pytest.raises(ValueError,match='Speaker leakage'):
        assert_speaker_partition([{'speaker':'same','split':'train'}, {'speaker':'same','split':'dev'}])


def test_other_and_low_margin_are_not_fabricated_nasal_directions():
    rows=[{'id':'a','speaker':'one','condition':'error','expected_label':'front','actual_label':'back'}]*3
    scores=np.array([[.1,.8,.1],[.1,.2,.7],[.4,.41,.1]])
    result=observe(rows,scores,.2)
    assert [r['candidate_nasal_change'] for r in result]==[True,False,False]
    summary=summarize(result)
    assert summary['correct_error_directions']==1
    assert summary['missed_error_directions']==2
    assert not any(r['candidate_nasal_change'] for r in observe(rows,scores,None))


def test_no_warning_is_not_the_same_as_correct_and_false_reassurance_is_counted():
    rows=[{'id':'a','speaker':'one','condition':'error','expected_label':'front','actual_label':'back'}]
    scores=np.array([[.8,.1,.1]])
    assert not observe(rows,scores,None)[0]['candidate_nasal_match']
    assert summarize(observe(rows,scores,None,0))['false_reassurances']==1
    assert summarize(observe(rows,scores,None,1))['false_reassurances']==0
