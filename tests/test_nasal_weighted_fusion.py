from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from nasal_weighted_fusion import WEIGHTS,feature_view,fit_weighted,predict_weighted
from nasal_feature_probe import fit_ridge,predict_ridge


def data():
    return np.random.default_rng(749).normal(size=(19,2,5)),np.array([0]*9+[1]*6+[2]*4)


@pytest.mark.parametrize('weight',[0.,1.])
def test_endpoints_replay_original_models_exactly(weight):
    x,y=data();old=fit_ridge(x[:,int(weight)],y,.1);new=fit_weighted(x,y,.1,weight)
    for key in old:np.testing.assert_array_equal(new[key],old[key])
    np.testing.assert_array_equal(predict_weighted(new,x,weight),predict_ridge(old,x[:,int(weight)]))


def test_half_weight_is_exact_original_concatenation():
    x,y=data();old=fit_ridge(x.reshape(19,-1),y,.1);new=fit_weighted(x,y,.1,.5)
    for key in old:np.testing.assert_array_equal(new[key],old[key])


@pytest.mark.parametrize('weight',[.25,.5,.75])
def test_each_standardized_block_receives_requested_training_energy(weight):
    x,y=data();model=fit_weighted(x,y,.1,weight);flat=x.reshape(19,-1)
    z=(flat-model['mean'])/model['scale']/np.sqrt(flat.shape[1])
    sample_weights=19/(3*np.bincount(y)[y])
    energies=np.average(z*z,axis=0,weights=sample_weights).reshape(2,5).sum(axis=1)
    np.testing.assert_allclose(energies,[1-weight,weight],rtol=1e-12,atol=1e-12)


@pytest.mark.parametrize('weight',[.25,.5,.75])
def test_dual_solution_agrees_with_independent_augmented_least_squares(weight):
    x,y=data();flat=x.reshape(19,-1);weights=19/(3*np.bincount(y)[y])
    mean=np.average(flat,axis=0,weights=weights)
    std=np.sqrt(np.average((flat-mean)**2,axis=0,weights=weights))
    z=((flat-mean)/std).reshape(19,2,5)*np.sqrt(np.array([1-weight,weight])/5)[None,:,None]
    z=z.reshape(19,-1);target=np.eye(3)[y];intercept=np.average(target,axis=0,weights=weights)
    a=np.vstack([z*np.sqrt(weights)[:,None],np.sqrt(.1)*np.eye(10)])
    b=np.vstack([(target-intercept)*np.sqrt(weights)[:,None],np.zeros((10,3))])
    coefficient=np.linalg.lstsq(a,b,rcond=None)[0]
    fitted=fit_weighted(x,y,.1,weight)
    np.testing.assert_allclose(predict_weighted(fitted,x,weight),z@coefficient+intercept,rtol=1e-11,atol=1e-11)


def test_input_units_do_not_cancel_requested_block_weights():
    x,y=data();rescaled=x.copy();rescaled[:,1]*=1000
    model=fit_weighted(x,y,.1,.25);other=fit_weighted(rescaled,y,.1,.25)
    np.testing.assert_allclose(predict_weighted(model,x,.25),predict_weighted(other,rescaled,.25),atol=1e-12)
    assert not np.allclose(predict_weighted(model,x,.25),predict_weighted(fit_weighted(x,y,.1,.75),x,.75))


def test_prediction_uses_saved_training_statistics_and_roundtrips(tmp_path):
    x,y=data();model=fit_weighted(x,y,.1,.25);snapshot={k:v.copy() for k,v in model.items()}
    query=np.full((3,2,5),1000.);before=predict_weighted(model,query,.25)
    for key in model:np.testing.assert_array_equal(model[key],snapshot[key])
    np.savez(tmp_path/'model.npz',**model)
    with np.load(tmp_path/'model.npz',allow_pickle=False) as stored:restored=dict(stored)
    np.testing.assert_array_equal(predict_weighted(restored,query,.25),before)


@pytest.mark.parametrize('weight',[-1.,.2,1.1,float('nan'),float('inf')])
def test_unregistered_weights_rejected(weight):
    with pytest.raises(ValueError,match='weight'):feature_view(data()[0],weight)


@pytest.mark.parametrize('value',[np.zeros((3,2)),np.zeros((3,3,5)),np.full((3,2,5),np.nan)])
def test_invalid_pair_matrix_rejected(value):
    with pytest.raises(ValueError,match='blocks'):feature_view(value,.5)


@pytest.mark.parametrize('strength',[0.,-1.,float('nan'),float('inf')])
def test_invalid_regularization_rejected(strength):
    x,y=data()
    with pytest.raises(ValueError,match='regularization'):fit_weighted(x,y,strength,.5)


def test_missing_class_is_not_silently_fitted():
    x,y=data()
    with pytest.raises(ValueError,match='classes'):fit_weighted(x,np.zeros(len(y)),.1,.5)
