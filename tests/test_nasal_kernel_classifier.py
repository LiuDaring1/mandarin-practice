from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from nasal_kernel_classifier import fit_kernel, predict_kernel, squared_distances
from nasal_feature_probe import fit_ridge, predict_ridge


def rows(labels):
    finals=('an','ang','a');names=('front','back','other')
    return [{'id':str(i),'split':'train','speaker':'source:'+str(i%3),
             'expected_final':finals[label],'expected_label':names[label],'actual_label':names[label],
             'label_source':'unanimous_vowel_scores'} for i,label in enumerate(labels)]


def sample():
    y=np.array([0]*3+[1]*5+[2]*7)
    return np.random.default_rng(7).normal(size=(len(y),4)),y


def test_squared_distance_matches_direct_euclidean_calculation():
    x,_=sample();y=np.random.default_rng(9).normal(size=(8,4))
    np.testing.assert_allclose(squared_distances(x,y),((x[:,None]-y[None])**2).sum(axis=-1),atol=1e-13)


def test_weighted_kernel_solution_matches_explicit_feature_space():
    x,y=sample();strength=.2;model=fit_kernel(x,rows(y),strength,.25)
    kernel=np.exp(-float(model['gamma'])*squared_distances(model['support'],model['support']))
    # Independent eigendecomposition feature map, then ordinary weighted ridge.
    values,vectors=np.linalg.eigh(kernel)
    phi=vectors*np.sqrt(np.maximum(values,0))[None,:]
    weights=len(y)/(3*np.bincount(y)[y])
    centered=phi-np.average(phi,axis=0,weights=weights)
    target=np.eye(3)[y];intercept=np.average(target,axis=0,weights=weights)
    coefficient=np.linalg.solve(centered.T@(weights[:,None]*centered)+strength*np.eye(len(y)),
        centered.T@(weights[:,None]*(target-intercept)))
    np.testing.assert_allclose(predict_kernel(model,x),centered@coefficient+intercept,atol=2e-12)
    np.testing.assert_allclose(np.average(predict_kernel(model,x),axis=0,weights=weights),[1/3]*3,atol=1e-13)


def test_permutation_does_not_change_bandwidth_or_prediction():
    x,y=sample();order=np.random.default_rng(8).permutation(len(y))
    one=fit_kernel(x,rows(y),.1,1.)
    reordered=fit_kernel(x[order],[rows(y)[i] for i in order],.1,1.)
    assert float(one['gamma'])==pytest.approx(float(reordered['gamma']),abs=1e-14)
    np.testing.assert_allclose(predict_kernel(one,x),predict_kernel(reordered,x),atol=1e-12)


def test_predicting_other_rows_cannot_change_normalization_or_bandwidth():
    x,y=sample();model=fit_kernel(x,rows(y),.1,1.)
    before={k:v.copy() for k,v in model.items()}
    solo=predict_kernel(model,x[:1]);batch=predict_kernel(model,np.concatenate((x[:1],np.full((1,x.shape[1]),1e6))))
    np.testing.assert_allclose(solo,batch[:1],atol=1e-12)
    for key in model: np.testing.assert_array_equal(model[key],before[key])


def test_saved_model_replays_exact_predictions(tmp_path):
    x,y=sample();model=fit_kernel(x,rows(y),.1,4.)
    path=tmp_path/'model.npz';np.savez_compressed(path,**model)
    with np.load(path,allow_pickle=False) as loaded: restored=dict(loaded)
    np.testing.assert_array_equal(predict_kernel(model,x),predict_kernel(restored,x))


def test_nonlinear_capacity_on_unseen_ring_positions():
    angles=np.arange(12)*2*np.pi/12
    train=np.concatenate([np.stack((np.cos(angles),np.sin(angles)),axis=1)*radius for radius in (1,2,3)])
    heldout=np.concatenate([np.stack((np.cos(angles+.1),np.sin(angles+.1)),axis=1)*radius for radius in (1,2,3)])
    labels=np.repeat(np.arange(3),12)
    kernel=fit_kernel(train,rows(labels),.001,.25)
    assert np.mean(predict_kernel(kernel,heldout).argmax(axis=1)==labels)>.95
    linear=fit_ridge(train,labels,.001)
    assert np.mean(predict_ridge(linear,heldout).argmax(axis=1)==labels)<.5


@pytest.mark.parametrize('split',['dev','test','holdout','transfer','validation'])
def test_evaluation_rows_cannot_enter_kernel_or_bandwidth(split):
    x,y=sample();targets=rows(y);targets[0]['split']=split
    with pytest.raises(ValueError,match='training rows only'): fit_kernel(x,targets,.1,1.)


def test_unverified_pseudo_targets_cannot_become_kernel_labels():
    x,y=sample();targets=rows(y);targets[0]['label_source']='unverified_expected_pseudo_target'
    with pytest.raises(ValueError,match='Unverified normal'): fit_kernel(x,targets,.1,1.)


def test_identical_features_cannot_create_a_fake_bandwidth():
    _,y=sample()
    with pytest.raises(ValueError,match='positive training distances'):
        fit_kernel(np.ones((len(y),4)),rows(y),.1,1.)


@pytest.mark.parametrize('strength,bandwidth',[(0,1),(-1,1),(float('nan'),1),(1,0),(1,-1),(1,float('inf'))])
def test_invalid_regularization_or_bandwidth_rejected(strength,bandwidth):
    x,y=sample()
    with pytest.raises(ValueError,match='Positive finite'): fit_kernel(x,rows(y),strength,bandwidth)


def test_nonfinite_or_wrong_dimension_features_rejected():
    x,y=sample();model=fit_kernel(x,rows(y),.1,1.)
    with pytest.raises(ValueError,match='Invalid kernel prediction'): predict_kernel(model,np.ones((3,5)))
    bad=x.copy();bad[0,0]=float('nan')
    with pytest.raises(ValueError,match='finite features'): fit_kernel(bad,rows(y),.1,1.)
    with pytest.raises(ValueError,match='Invalid kernel prediction'): predict_kernel(model,bad)


def test_tied_development_prefers_original_linear_model():
    from probe_nasal_kernel import rank
    base={'development':{'correct_error_directions':10,'correct_nasal_matches':20},'regularization':.1,'bandwidth_multiplier':0.}
    linear={**base,'kind':'linear'};kernel={**base,'kind':'rbf','regularization':1.,'bandwidth_multiplier':4.}
    assert rank(linear)<rank(kernel)
