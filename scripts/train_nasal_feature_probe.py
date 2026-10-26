"""Fit/select on train/dev, then separately evaluate the locked classifier."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from nasal_feature_probe import (LABELS, LAYERS, assert_speaker_partition,
                                balanced_accuracy, feature_view, predict_ridge,
                                select_on_development)


def save_json(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');path.chmod(0o600)


def load_features(folder):
    dataset_path = folder/'dataset.json'
    dataset = json.loads(dataset_path.read_text())
    index = json.loads((folder/'feature-index.json').read_text())
    if index.get('complete') is not True or index['dataset_sha256'] != hashlib.sha256(dataset_path.read_bytes()).hexdigest():
        raise ValueError('Incomplete/stale feature index')
    lookup = {r['id']:r for r in dataset['rows']}
    rows, features = [], []
    for entry in index['rows']:
        with np.load(entry['cache'],allow_pickle=False) as data:
            if data['ids'][entry['index']] != entry['id']:
                raise ValueError('Feature/label identity mismatch')
            features.append(data['features'][entry['index']])
            rows.append(lookup[entry['id']])
    assert_speaker_partition(rows)
    return np.stack(features), rows, dataset, index


def observe(rows, scores, margin=0, matching_margin=None):
    ordered = np.sort(scores,axis=1)
    gaps = ordered[:,-1]-ordered[:,-2]
    result = []
    for row,score,gap in zip(rows,scores,gaps):
        predicted = LABELS[int(score.argmax())]
        usable = margin is not None and gap >= margin
        direction = (usable and predicted in ('front','back') and row['expected_label'] in ('front','back')
                     and predicted != row['expected_label'])
        matching = (matching_margin is not None and gap >= matching_margin
                    and row['expected_label'] in ('front','back') and predicted==row['expected_label'])
        result.append({'id':row['id'],'speaker':row['speaker'],'condition':row['condition'],
                       'expected':row['expected_label'],'actual':row['actual_label'],
                       'predicted':predicted,'gap':float(gap),'scores':score.tolist(),
                       'candidate_nasal_change':bool(direction),'candidate_nasal_match':bool(matching)})
    return result


def summarize(observations):
    y = [LABELS.index(r['actual']) for r in observations]
    p = [LABELS.index(r['predicted']) for r in observations]
    matrix = [[sum(a==i and b==j for a,b in zip(y,p)) for j in range(3)] for i in range(3)]
    errors = [r for r in observations if r['expected'] in ('front','back') and r['actual'] != r['expected']]
    normal = [r for r in observations if r['expected'] in ('front','back') and r['actual'] == r['expected']]
    return {'targets':len(observations), 'label_order':LABELS, 'confusion_matrix':matrix,
            'balanced_label_accuracy':balanced_accuracy(y,p) if y else None,
            'known_nasal_errors':len(errors),
            'correct_error_directions':sum(r['candidate_nasal_change'] and r['predicted']==r['actual'] for r in errors),
            'missed_error_directions':sum(not (r['candidate_nasal_change'] and r['predicted']==r['actual']) for r in errors),
            'raw_expected_label_on_error':sum(r['predicted']==r['expected'] for r in errors),
            'correct_nasal_targets':len(normal),
            'false_nasal_accusations':sum(r['candidate_nasal_change'] for r in normal),
            'false_reassurances':sum(r['candidate_nasal_match'] for r in errors),
            'correct_nasal_matches':sum(r['candidate_nasal_match'] for r in normal),
            'uncertain_nasal_targets':sum(not r['candidate_nasal_match'] and not r['candidate_nasal_change']
                                          for r in errors+normal)}


def select_margin(rows, scores):
    if any(r['split'] != 'dev' for r in rows):
        raise ValueError('Margin selection must use development data only')
    candidates=[]
    for margin in (0.,.05,.1,.2,.3,.5,.75,1.):
        counts = summarize(observe(rows,scores,margin))
        candidates.append({'margin':margin,**counts})
    acceptable=[c for c in candidates if c['false_nasal_accusations']==0 and c['correct_error_directions']>=3]
    best=max(acceptable,key=lambda c:(c['correct_error_directions'],-c['margin'])) if acceptable else None
    return best['margin'] if best else None,candidates


def select_matching_margin(rows,scores):
    if any(r['split']!='dev' for r in rows):
        raise ValueError('Matching calibration must use development data only')
    candidates=[]
    for margin in (0.,.05,.1,.2,.3,.5,.75,1.):
        counts=summarize(observe(rows,scores,None,margin))
        candidates.append({'margin':margin,**counts})
    acceptable=[r for r in candidates if r['false_reassurances']==0 and r['correct_nasal_matches']>=5]
    best=max(acceptable,key=lambda r:(r['correct_nasal_matches'],-r['margin'])) if acceptable else None
    return best['margin'] if best else None,candidates


def main(args):
    folder=Path(args.directory)
    features,rows,dataset,index=load_features(folder)
    selection_path=folder/'selection.json';weights_path=folder/'ridge-model.npz'
    if args.mode=='fit':
        if selection_path.exists() or weights_path.exists():
            raise ValueError('Selection already frozen; use evaluation, not silent retuning')
        fit_indices=[i for i,r in enumerate(rows) if r['split'] in ('train','dev')]
        fit_rows=[rows[i] for i in fit_indices]
        best,model,ranking=select_on_development(features[fit_indices],fit_rows)
        dev_indices=[i for i,r in enumerate(rows) if r['split']=='dev']
        dev_features=feature_view(features[dev_indices],LAYERS.index(best['layer']),best['view'])
        dev_scores=predict_ridge(model,dev_features)
        margin,margin_table=select_margin([rows[i] for i in dev_indices],dev_scores)
        matching_margin,matching_table=select_matching_margin([rows[i] for i in dev_indices],dev_scores)
        np.savez_compressed(weights_path,**model);weights_path.chmod(0o600)
        selection={'selected_at_utc':datetime.now(timezone.utc).isoformat(),'selected':best,
                   'review_margin':margin,'margin_rule':'zero development false nasal accusations and at least three detected errors; otherwise no review suggestions',
                   'matching_margin':matching_margin,'matching_margin_rule':'zero development false reassurance and at least five correctly matched normal nasal targets',
                   'weights_sha256':hashlib.sha256(weights_path.read_bytes()).hexdigest(),
                   'dataset_sha256':index['dataset_sha256'],'grid':ranking,'development_margin_table':margin_table,
                   'development_matching_table':matching_table,
                   'evaluation_rows_used_for_selection':False,'encoder_frozen':True,
                   'train_ids':[r['id'] for r in fit_rows if r['split']=='train'],
                   'dev_ids':[r['id'] for r in fit_rows if r['split']=='dev']}
        save_json(selection_path,selection)
        print(json.dumps({'selected':best,'review_margin':margin,'matching_margin':matching_margin},ensure_ascii=False),flush=True)
        return
    selection=json.loads(selection_path.read_text())
    if selection['dataset_sha256'] != index['dataset_sha256'] or selection['weights_sha256'] != hashlib.sha256(weights_path.read_bytes()).hexdigest():
        raise ValueError('Frozen selection/model changed')
    with np.load(weights_path,allow_pickle=False) as data:
        model={name:data[name] for name in ('mean','scale','coefficient','intercept')}
    selected=selection['selected'];reports={};predictions=[]
    for split in ('train','dev','test','transfer'):
        positions=[i for i,r in enumerate(rows) if r['split']==split]
        subset=[rows[i] for i in positions]
        x=feature_view(features[positions],LAYERS.index(selected['layer']),selected['view'])
        scores=predict_ridge(model,x)
        observations=observe(subset,scores,selection['review_margin'],selection.get('matching_margin'))
        predictions.extend(dict(r,split=split) for r in observations)
        reports[split]={'selected_margin':summarize(observations),
                        'without_margin':summarize(observe(subset,scores,0,0)),
                        'excluded_alignment':sum(r['split']==split for r in dataset['excluded']),
                        'excluded_pooling':sum(any(r['id']==x['id'] and r['split']==split for r in dataset['rows']) for x in index['excluded'])}
    report={'complete':True,'selection':{k:selection[k] for k in ('selected','review_margin','matching_margin','dataset_sha256','weights_sha256') if k in selection},
            'splits':reports,'predictions':predictions,
            'limits':['Speaker separation within this fit, not untouched final product validation.',
                      'Word source crop and vendor interval errors remain possible.',
                      'Ridge score gaps are not correctness probabilities.',
                      'The detector has not been deployed or tested with a live microphone.']}
    save_json(folder/'evaluation.json',report)
    print(json.dumps(reports,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['fit','evaluate'])
    parser.add_argument('--directory',default='data/derived/nasal-acoustic-validation/feature-classifier-v1')
    main(parser.parse_args())
