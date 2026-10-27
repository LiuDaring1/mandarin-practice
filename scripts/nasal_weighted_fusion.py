"""Training-only block normalization with explicit acoustic energy weights."""
import numpy as np

from nasal_feature_probe import LABELS,fit_ridge,predict_ridge

WEIGHTS=(0.,.25,.5,.75,1.)


def feature_view(paired,hubert_weight):
    x=np.asarray(paired)
    if hubert_weight not in WEIGHTS:raise ValueError('Unregistered HuBERT weight')
    if x.ndim!=3 or x.shape[1]!=2 or x.shape[2]<1 or not np.isfinite(x).all():
        raise ValueError('Expected finite paired acoustic blocks')
    if hubert_weight==0.:return x[:,0]
    if hubert_weight==1.:return x[:,1]
    return x.reshape(len(x),-1)


def fit_weighted(paired,labels,regularization,hubert_weight):
    x=np.asarray(feature_view(paired,hubert_weight),dtype=np.float64)
    y=np.asarray(labels,dtype=np.int64)
    if (y.ndim!=1 or len(x)!=len(y) or not len(y) or set(y.tolist())!=set(range(len(LABELS)))
            or not np.isfinite(regularization) or regularization<=0):
        raise ValueError('Need all classes and finite positive regularization')
    if hubert_weight in (0.,1.):return fit_ridge(x,y,regularization)
    counts=np.bincount(y,minlength=len(LABELS));weights=len(y)/(len(LABELS)*counts[y])
    mean=np.average(x,axis=0,weights=weights)
    scale=np.maximum(np.sqrt(np.average((x-mean)**2,axis=0,weights=weights)),1e-4)
    width=x.shape[1]//2
    # Apply AFTER normalization; scaling raw features would cancel out during
    # standardization. predict_ridge's sqrt(total dimension) stays unchanged.
    scale*=np.repeat(np.sqrt(1/(2*np.array([1-hubert_weight,hubert_weight]))),width)
    z=(x-mean)/scale/np.sqrt(x.shape[1]);target=np.eye(len(LABELS))[y]
    intercept=np.average(target,axis=0,weights=weights);root=np.sqrt(weights)[:,None];a=z*root
    dual=np.linalg.solve(a@a.T+regularization*np.eye(len(x)),(target-intercept)*root)
    return {'mean':mean,'scale':scale,'coefficient':a.T@dual,'intercept':intercept}


def predict_weighted(model,paired,hubert_weight):
    return predict_ridge(model,feature_view(paired,hubert_weight))
