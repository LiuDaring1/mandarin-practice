"""Refit the fixed v3 acoustic head with sentence-error training examples.

The encoder/layer/view/regularization are fixed before new sentence evaluation.
Only decision margins use development rows. API contradictions veto positive
claims; they do not automatically identify the direction of a nasal error.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from audit_nasal_feedback_conflicts import veto_conflict
from nasal_feature_probe import LABELS,LAYERS,feature_view,fit_ridge,predict_ridge
from select_nasal_feedback_probe import review_rule
from train_nasal_feature_probe import load_features,observe,save_json,summarize


def policy_observations(rows,scores,review_margin,matching_margin):
    observed=observe(rows,scores,review_margin,matching_margin)
    return [{**veto_conflict(obs,row['api_state']),'cohort':row.get('cohort','previous'),
             'split':row['split']} for obs,row in zip(observed,rows)]


def matching_rule(rows,scores):
    if not rows or any(r['split']!='dev' for r in rows):
        raise ValueError('Matching selection requires development rows only')
    table=[]
    for margin in (0.,.05,.1,.2,.3,.5,.75,1.):
        table.append({'margin':margin,**summarize(policy_observations(rows,scores,None,margin))})
    eligible=[r for r in table if r['false_reassurances']==0 and r['correct_nasal_matches']>=5]
    best=max(eligible,key=lambda r:(r['correct_nasal_matches'],-r['margin'])) if eligible else None
    return best['margin'] if best else None,table


def grouped(observations):
    groups={split:summarize([r for r in observations if r['split']==split])
            for split in sorted({r['split'] for r in observations})}
    new=[r for r in observations if r['cohort']=='new_sentence' and r['split'] not in ('train','dev')]
    groups['new_sentence_evaluation']=summarize(new)
    groups['new_sentence_directions']={expected:summarize([r for r in new if r['expected']==expected])
                                       for expected in ('front','back')}
    return groups


def main(args):
    folder=Path(args.directory)
    base=folder.parent
    plan_path=base/'context-training-v4-plan.json';plan=json.loads(plan_path.read_text())
    baseline_folder=base/plan['baseline']
    baseline=json.loads((baseline_folder/'selection.json').read_text())
    specification=baseline['selected']
    for key in ['layer','view','regularization']:
        if specification[key]!=plan[key]:
            raise ValueError('Fixed architecture differs from pre-evaluation plan')
    features,rows,dataset,index=load_features(folder)
    if index['model']['repo']!='facebook/wav2vec2-xlsr-53-espeak-cv-ft':
        raise ValueError('Context experiment requires the fixed phoneme encoder')
    x=feature_view(features,LAYERS.index(plan['layer']),plan['view'])
    weights=folder/'ridge-model.npz';selection_path=folder/'selection.json'
    if args.mode=='fit':
        if weights.exists() or selection_path.exists():
            raise ValueError('Context model selection is already frozen')
        training=np.array([r['split']=='train' for r in rows]);dev=np.array([r['split']=='dev' for r in rows])
        labels=np.array([LABELS.index(r['actual_label']) for r in rows])
        model=fit_ridge(x[training],labels[training],plan['regularization'])
        dev_rows=[r for r in rows if r['split']=='dev'];scores=predict_ridge(model,x[dev])
        review,review_table=review_rule(dev_rows,scores)
        matching,matching_table=matching_rule(dev_rows,scores)
        np.savez_compressed(weights,**model);weights.chmod(0o600)
        selected={k:plan[k] for k in ['encoder','layer','view','regularization']}
        selected.update(review_margin=review['margin'] if review else None,matching_margin=matching,api_positive_veto=True)
        selection={'selected_at_utc':datetime.now(timezone.utc).isoformat(),'selected':selected,
                   'dataset_sha256':index['dataset_sha256'],'weights_sha256':hashlib.sha256(weights.read_bytes()).hexdigest(),
                   'plan_sha256':hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                   'baseline_weights_sha256':baseline['weights_sha256'],
                   'development_review_table':review_table,'development_matching_table':matching_table,
                   'train_ids':[r['id'] for r in rows if r['split']=='train'],
                   'dev_ids':[r['id'] for r in rows if r['split']=='dev'],
                   'evaluation_rows_used_for_selection':False}
        save_json(selection_path,selection);print(json.dumps(selected),flush=True)
        return
    output=folder/'evaluation.json'
    if output.exists():
        raise ValueError('Context evaluation is frozen')
    selection=json.loads(selection_path.read_text())
    if selection['dataset_sha256']!=index['dataset_sha256'] or selection['plan_sha256']!=hashlib.sha256(plan_path.read_bytes()).hexdigest():
        raise ValueError('Frozen context data/plan changed')
    reports={}
    for name,weight_path,selected,expected_hash in [
            ('baseline_v3',baseline_folder/'ridge-model.npz',specification,selection['baseline_weights_sha256']),
            ('context_v4',weights,selection['selected'],selection['weights_sha256'])]:
        if hashlib.sha256(weight_path.read_bytes()).hexdigest()!=expected_hash:
            raise ValueError('Frozen classifier weights changed')
        with np.load(weight_path,allow_pickle=False) as data:
            model={k:data[k] for k in ('mean','scale','coefficient','intercept')}
        scores=predict_ridge(model,x)
        observations=policy_observations(rows,scores,selected['review_margin'],selected['matching_margin'])
        reports[name]={'groups':grouped(observations),'predictions':observations}
    report={'complete':True,'dataset_sha256':index['dataset_sha256'],'selected':selection['selected'],
            'comparison':reports,'excluded_targets':len(dataset['excluded'])+len(index['excluded']),
            'limits':['Old test/transfer targets were explored previously.',
                      'New sentence evaluation contains errors but no new matched normal controls.',
                      'API boundaries and long-audio context windows need independent audit.',
                      'No noise/live microphone/production feedback validation.']}
    save_json(output,report)
    for name,value in reports.items():
        print(name,json.dumps(value['groups'],ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['fit','evaluate'])
    parser.add_argument('--directory',default='data/derived/nasal-acoustic-validation/context-training-v4')
    main(parser.parse_args())
