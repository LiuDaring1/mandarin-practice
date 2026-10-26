"""Train a small nasal head on frozen Xeus features, without test tuning."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path

import numpy as np

from extract_xeus_features import FOLDER,PHONE,sha256
from fit_nasal_local_context import selected_rows
from nasal_feature_probe import LABELS,assert_speaker_partition,feature_view,fit_ridge,predict_ridge
from probe_nasal_boundaries import summarize_denominator
from probe_phonetic_xeus import apply,calibrate,cohort_summary
from train_nasal_feature_probe import save_json


def prepare():
    if FOLDER.exists():raise ValueError('Xeus feature plan frozen')
    base=FOLDER.parent
    sources=[base/'context-training-v4/dataset.json',base/'griffith-external-v2/dataset.json',
             PHONE/'model-source.json',PHONE/'runtime-source.json',PHONE/'evaluation.json',
             base/'ise-word-calibration-input.json',base/'feedback-v3-holdout/input.json',base/'context-training-v4/input.json']
    sources += [Path('scripts')/n for n in ['fit_xeus_features.py','extract_xeus_features.py','phonetic_xeus.py',
                'nasal_feature_probe.py','nasal_directional_calibration.py','probe_phonetic_xeus.py',
                'calibrate_nasal_exact_margin.py','fit_nasal_local_context.py','zipa_context.py']]
    plan={'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'sources':{str(p):sha256(p) for p in sources},
          'layers':[8,12,19],'view':'trajectory','regularizations':[.01,.1,1.],
          'calibration_modes':['global','directional'],'selection_splits':['train','dev'],
          'context':'Same natural 20s maximum context and parent normalization as Xeus phone experiment.',
          'ranking':['development correct error directions','development correct normal matches',
                     'stronger regularization','earlier layer','global calibration first'],
          'evaluation_previously_explored':True,'encoder_training':False,'expected_text_feature':False}
    FOLDER.mkdir();save_json(FOLDER/'plan.json',plan)
    for cohort,source in [('existing',base/'context-training-v4/dataset.json'),('griffith',base/'griffith-external-v2/dataset.json')]:
        dataset=json.loads(source.read_text())
        if cohort=='existing':
            restored={r['id']:r for r in selected_rows(dataset)}
            dataset['excluded']=[restored[r['id']] for r in dataset['excluded']]
        save_json(FOLDER/f'{cohort}-dataset.json',{**dataset,'plan_sha256':sha256(FOLDER/'plan.json')})


def checked():
    plan=json.loads((FOLDER/'plan.json').read_text())
    if any(sha256(Path(p))!=v for p,v in plan['sources'].items()):raise ValueError('Frozen feature sources changed')
    return plan


def load(cohort):
    plan=checked();dataset=json.loads((FOLDER/f'{cohort}-dataset.json').read_text())
    index=json.loads((FOLDER/f'{cohort}-feature-index.json').read_text())
    if (index.get('complete') is not True or index['plan_sha256']!=sha256(FOLDER/'plan.json')
        or index['dataset_sha256']!=sha256(FOLDER/f'{cohort}-dataset.json') or index['layers']!=plan['layers']):
        raise ValueError('Incomplete/stale feature index')
    lookup={r['id']:r for r in dataset['rows']};rows=[];features=[]
    for record in index['rows']:
        with np.load(record['cache'],allow_pickle=False) as data:
            if data['ids'][record['index']]!=record['id']:raise ValueError('Feature ID mismatch')
            features.append(data['features'][record['index']]);rows.append(lookup[record['id']])
    if len({r['id'] for r in rows})!=len(rows):raise ValueError('Duplicate features')
    assert_speaker_partition(rows)
    return rows,np.stack(features),dataset


def fit():
    plan=checked();output=FOLDER/'selection.json'
    if output.exists() or (FOLDER/'ridge-model.npz').exists():raise ValueError('Feature model already frozen')
    rows,features,dataset=load('existing');positions=[i for i,r in enumerate(rows) if r['split'] in ('train','dev')]
    subset=[rows[i] for i in positions];features=features[positions];assert_speaker_partition(subset)
    training=np.array([r['split']=='train' for r in subset]);dev=~training
    labels=np.array([LABELS.index(r['actual_label']) for r in subset]);dev_rows=[r for r in subset if r['split']=='dev']
    denominator=[r for r in dataset['rows']+dataset['excluded'] if r['split']=='dev']
    candidates=[]
    for layer in plan['layers']:
        x=feature_view(features,plan['layers'].index(layer),plan['view'])
        for strength in plan['regularizations']:
            model=fit_ridge(x[training],labels[training],strength);scores=predict_ridge(model,x[dev])
            for mode in plan['calibration_modes']:
                policy=calibrate(dev_rows,scores,mode)
                candidate={**policy,'layer':layer,'view':plan['view'],'regularization':strength,
                           'development':summarize_denominator(denominator,apply(dev_rows,scores,policy))}
                candidates.append(candidate)
                print('CANDIDATE',layer,strength,mode,candidate['development']['correct_error_directions'],candidate['development']['correct_nasal_matches'],flush=True)
    candidates.sort(key=lambda c:(-c['development']['correct_error_directions'],-c['development']['correct_nasal_matches'],
                                   -c['regularization'],c['layer'],plan['calibration_modes'].index(c['calibration_mode'])))
    best=candidates[0];x=feature_view(features,plan['layers'].index(best['layer']),best['view'])
    model=fit_ridge(x[training],labels[training],best['regularization'])
    weights=FOLDER/'ridge-model.npz';np.savez_compressed(weights,**model);weights.chmod(0o600)
    save_json(output,{'selected':best,'ranking':candidates,'selected_at_utc':datetime.now(timezone.utc).isoformat(),
        'plan_sha256':sha256(FOLDER/'plan.json'),'feature_index_sha256':sha256(FOLDER/'existing-feature-index.json'),
        'weights_sha256':sha256(weights),'train_ids':[r['id'] for r in subset if r['split']=='train'],
        'dev_ids':[r['id'] for r in dev_rows],'evaluation_rows_used_for_selection':False})
    print('FEATURE HEAD SELECTED',best['layer'],best['regularization'],best['calibration_mode'],flush=True)


def evaluate():
    plan=checked();output=FOLDER/'evaluation.json'
    if output.exists():raise ValueError('Feature evaluation frozen')
    selection=json.loads((FOLDER/'selection.json').read_text());chosen=selection['selected']
    if selection['plan_sha256']!=sha256(FOLDER/'plan.json') or selection['weights_sha256']!=sha256(FOLDER/'ridge-model.npz'):
        raise ValueError('Frozen model changed')
    if selection['feature_index_sha256']!=sha256(FOLDER/'existing-feature-index.json'):raise ValueError('Training feature index changed')
    with np.load(FOLDER/'ridge-model.npz',allow_pickle=False) as stored:model={k:stored[k] for k in stored.files}
    comparison={}
    for cohort in ('existing','griffith'):
        rows,features,dataset=load(cohort)
        scores=predict_ridge(model,feature_view(features,plan['layers'].index(chosen['layer']),chosen['view']))
        observed=apply(rows,scores,chosen)
        # Evaluation reports only nasal targets; other classes still train the head.
        nasal_dataset={k:[r for r in dataset[k] if r['expected_label'] in ('front','back')] for k in ('rows','excluded')}
        comparison[cohort]=cohort_summary(nasal_dataset,[r for r in observed if r['expected'] in ('front','back')])
        print(cohort,json.dumps(comparison[cohort]['evaluation_only']),flush=True)
    save_json(output,{'complete':True,'selected':chosen,'comparison':comparison,'selection_sha256':sha256(FOLDER/'selection.json'),
        'evaluation_previously_explored':True,'limits':['No new blind set or production integration.',
        'Frozen encoder, small trained head; API timing remains approximate.', 'No noise/real-device validation for this newly trained head.']})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','fit','evaluate'])
    args=parser.parse_args();{'prepare':prepare,'fit':fit,'evaluate':evaluate}[args.mode]()
