"""Evaluate a frozen feedback classifier; never fits or selects parameters."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from nasal_feature_probe import LAYERS, feature_view, predict_ridge
from train_nasal_feature_probe import load_features, observe, save_json, summarize


def validate_holdout(rows, original):
    fit_speakers = {r['speaker'] for r in original if r['split'] in ('train','dev')}
    if any(r['speaker'] in fit_speakers for r in rows):
        raise ValueError('External holdout shares a fitting/development speaker')
    if any(r['split'] != 'holdout' for r in rows):
        raise ValueError('External evaluation must contain holdout rows only')


def main(args):
    folder = Path(args.model_directory)
    selection = json.loads((folder/'selection.json').read_text())
    source = Path(selection['source_directory'])
    external = Path(args.data_directory) if args.data_directory else source
    output = Path(args.output) if args.output else folder/'evaluation.json'
    if output.exists():
        raise ValueError('Frozen evaluation already exists')
    features, rows, dataset, index = load_features(external)
    source_index = json.loads((source/'feature-index.json').read_text())
    if index['model'] != source_index['model'] or index['layers'] != source_index['layers'] or index['regions'] != source_index['regions']:
        raise ValueError('Evaluation encoder/features do not match the frozen model')
    if not args.data_directory and index['dataset_sha256'] != selection['dataset_sha256']:
        raise ValueError('Frozen model data changed')
    if args.data_directory:
        original = json.loads((source/'dataset.json').read_text())['rows']
        validate_holdout(rows,original)
    weights = folder/'ridge-model.npz'
    if hashlib.sha256(weights.read_bytes()).hexdigest() != selection['weights_sha256']:
        raise ValueError('Frozen weights changed')
    with np.load(weights, allow_pickle=False) as data:
        model = {k:data[k] for k in ('mean','scale','coefficient','intercept')}
    selected = selection['selected']
    predictions, reports = [], {}
    for split in sorted({r['split'] for r in rows}):
        positions = [i for i,r in enumerate(rows) if r['split'] == split]
        subset = [rows[i] for i in positions]
        x = feature_view(features[positions], LAYERS.index(selected['layer']), selected['view'])
        scores = predict_ridge(model,x)
        observed = observe(subset,scores,selected['review_margin'],selected['matching_margin'])
        predictions.extend(dict(r,split=split) for r in observed)
        reports[split] = {'selected_margin': summarize(observed),
                          'without_margin': summarize(observe(subset,scores,0,0)),
                          'excluded_alignment': sum(r['split']==split for r in dataset['excluded']),
                          'excluded_pooling': sum(any(r['id']==e['id'] and r['split']==split for r in dataset['rows']) for e in index['excluded'])}
    result = {'complete':True, 'selected':{k:selected[k] for k in ('encoder','layer','view','regularization','review_margin','matching_margin')},
              'dataset_sha256':index['dataset_sha256'], 'weights_sha256':selection['weights_sha256'],
              'splits':reports, 'predictions':predictions,
              'limits':['No live microphone or deployment validation.', 'Score margins are not correctness probabilities.']}
    save_json(output,result)
    print(json.dumps(reports,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--model-directory',required=True)
    parser.add_argument('--data-directory')
    parser.add_argument('--output')
    main(parser.parse_args())
