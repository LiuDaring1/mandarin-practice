from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from nasal_feature_probe import LABELS
from nasal_pair_classifier import audit_training, fit_heads as old_fit, pack_heads, predict_heads as old_predict, unpack_heads
from nasal_weighted_fusion import fit_weighted, predict_weighted
from nasal_weighted_pairs import fit_heads, predict_heads


def fixture():
    rows=[]
    for family in ('an','in'):
        for speaker in ('a','b'):
            for final,label in [(family,'front'),(family+'g','back')]:
                rows.append({'id':str(len(rows)),'speaker':speaker,'split':'train','expected_final':final,
                    'expected_label':label,'actual_label':label,'label_source':'unanimous_vowel_scores'})
    rows += [{'id':'8','speaker':'a','split':'train','expected_final':'a','expected_label':'other',
              'actual_label':'other','label_source':'native_score'},
             {'id':'9','speaker':'c','split':'train','expected_final':'an','expected_label':'front',
              'actual_label':'back','label_source':'explicit_nasal_substitution'}]
    return rows,np.random.default_rng(128).normal(size=(len(rows),2,7)),audit_training(rows,2,2)


@pytest.mark.parametrize('hw',[0.,1.])
def test_endpoint_all_heads_and_predictions_replay_previous_algorithm(hw):
    rows,x,support=fixture();new=fit_heads(x,rows,.1,support,hw);old=old_fit(x[:,int(hw)],rows,.1,support)
    assert set(new)==set(old)=={'shared','an','in'}
    for key in new:
        for field in new[key]:np.testing.assert_array_equal(new[key][field],old[key][field])
    finals=[r['expected_final'] for r in rows]
    for blend in (0.,.5,1.):
        np.testing.assert_array_equal(predict_heads(new,x,finals,blend,hw),old_predict(old,x[:,int(hw)],finals,blend))


@pytest.mark.parametrize('hw',[0.,.25,1.])
def test_zero_blend_exactly_replays_shared_fusion(hw):
    rows,x,support=fixture();heads=fit_heads(x,rows,.1,support,hw)
    old=fit_weighted(x,np.array([LABELS.index(r['actual_label']) for r in rows]),.1,hw)
    np.testing.assert_array_equal(predict_heads(heads,x,[r['expected_final'] for r in rows],0.,hw),predict_weighted(old,x,hw))


@pytest.mark.parametrize('hw',[0.,.25,1.])
def test_both_expected_directions_use_identical_acoustic_score(hw):
    rows,x,support=fixture();heads=fit_heads(x,rows,.1,support,hw)
    left=['an','in','en','ian','un','uan'];right=['ang','ing','eng','iang','ueng','uang']
    for blend in (0.,.5,1.):
        np.testing.assert_array_equal(predict_heads(heads,x[:6],left,blend,hw),predict_heads(heads,x[:6],right,blend,hw))


def test_specialist_training_weights_apply_after_its_own_class_standardization():
    rows,x,support=fixture();heads=fit_heads(x,rows,.1,support,.25)
    # Independent labels: same-family front/back, every other family is other.
    y=np.array([0,1,0,1,2,2,2,2,2,1]);weights=len(y)/(3*np.bincount(y)[y])
    head=heads['an'];z=(x.reshape(len(x),-1)-head['mean'])/head['scale']/np.sqrt(14)
    energy=np.average(z*z,axis=0,weights=weights).reshape(2,7).sum(axis=1)
    np.testing.assert_allclose(energy,[.75,.25],atol=1e-12)


def test_unsupported_family_keeps_shared_prediction_and_saved_state(tmp_path):
    rows,x,support=fixture();heads=fit_heads(x,rows,.1,support,.25)
    np.savez(tmp_path/'heads.npz',**pack_heads(heads))
    with np.load(tmp_path/'heads.npz',allow_pickle=False) as values:restored=unpack_heads(dict(values))
    query=np.full((4,2,7),300.);finals=['uan','uang','a','en']
    before={k:v.copy() for k,v in pack_heads(restored).items()}
    np.testing.assert_array_equal(predict_heads(restored,query,finals,1.,.25),predict_weighted(restored['shared'],query,.25))
    for k,v in pack_heads(restored).items():np.testing.assert_array_equal(v,before[k])


@pytest.mark.parametrize('change',[{'split':'dev'},{'label_source':'unmarked'},{'expected_final':'ang'}])
def test_evaluation_unverified_or_conflicting_labels_cannot_enter_training(change):
    rows,x,support=fixture();rows[0].update(change)
    with pytest.raises(ValueError):fit_heads(x,rows,.1,support,.25)


def test_changed_support_and_mismatched_features_are_rejected():
    rows,x,support=fixture()
    with pytest.raises(ValueError,match='support changed'):fit_heads(x,rows,.1,{**support,'eligible_pairs':[]},.25)
    with pytest.raises(ValueError):fit_heads(x[:-1],rows,.1,support,.25)


def test_invalid_blend_and_target_count_are_rejected():
    rows,x,support=fixture();heads=fit_heads(x,rows,.1,support,.25)
    for blend in (-.1,1.1,np.nan,np.inf):
        with pytest.raises(ValueError,match='weight'):predict_heads(heads,x,['an']*len(x),blend,.25)
    with pytest.raises(ValueError,match='identity count'):predict_heads(heads,x,[],.5,.25)
