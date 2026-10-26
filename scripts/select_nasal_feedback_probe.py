"""Research selection for the feedback task, using train/dev data only.

Previous classifiers selected general three-class accuracy before checking
review risk. This experiment selects useful error directions with no observed
development false accusations. Zero observed errors is NOT a population bound.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from nasal_feature_probe import (LABELS, LAYERS, assert_speaker_partition,
                                feature_view, fit_ridge, predict_ridge)
from train_nasal_feature_probe import (load_features, observe, save_json,
                                     select_matching_margin, summarize)


def review_rule(rows, scores):
    if not rows or any(r['split'] != 'dev' for r in rows):
        raise ValueError('Feedback selection requires development rows only')
    table = []
    for margin in (0., .05, .1, .2, .3, .5, .75, 1.):
        observations = observe(rows, scores, margin)
        counts = summarize(observations)
        directions = {group: sum(r['expected'] == group and r['predicted'] == r['actual']
                                  and r['candidate_nasal_change'] for r in observations)
                      for group in ('front', 'back')}
        table.append({'margin': margin, **counts, 'directions_by_expected': directions})
    eligible = [r for r in table if r['false_nasal_accusations'] == 0
                and r['correct_error_directions'] >= 3
                and all(r['directions_by_expected'].values())]
    best = max(eligible, key=lambda r: (r['correct_error_directions'], -r['margin'])) if eligible else None
    return best, table


def fit_candidates(features, rows, encoder):
    if any(r['split'] not in ('train', 'dev') for r in rows):
        raise ValueError('Feedback selection cannot receive test/transfer rows')
    assert_speaker_partition(rows)
    train = np.array([r['split'] == 'train' for r in rows])
    dev = np.array([r['split'] == 'dev' for r in rows])
    if not train.any() or not dev.any():
        raise ValueError('Need train and development rows')
    labels = np.array([LABELS.index(r['actual_label']) for r in rows])
    dev_rows = [r for r in rows if r['split'] == 'dev']
    candidates = []
    for layer_index, layer in enumerate(LAYERS):
        for view in ('syllable', 'vowel', 'last_half', 'trajectory'):
            x = feature_view(features, layer_index, view)
            for strength in (.001, .01, .1, 1., 10.):
                model = fit_ridge(x[train], labels[train], strength)
                scores = predict_ridge(model, x[dev])
                best, table = review_rule(dev_rows, scores)
                matching, matching_table = select_matching_margin(dev_rows, scores)
                counts = summarize(observe(dev_rows, scores, best['margin'] if best else None, matching))
                candidates.append({'encoder': encoder, 'layer': layer, 'view': view,
                                   'regularization': strength, 'review_margin': best['margin'] if best else None,
                                   'matching_margin': matching, 'development': counts,
                                   'directions_by_expected': best['directions_by_expected'] if best else {},
                                   'development_margin_table': table,
                                   'development_matching_table': matching_table})
    return candidates


def rank_candidates(candidates):
    # Both directions and >=3 errors are enforced by review_rule. General
    # accuracy only breaks ties after the actual feedback objectives.
    return sorted(candidates, key=lambda r: (
        -r['development']['correct_error_directions'],
        -r['development']['correct_nasal_matches'],
        -r['development']['balanced_label_accuracy'],
        -r['regularization'], r['layer'], r['view'], r['encoder']))


def main(args):
    output = Path(args.output)
    if output.exists():
        raise ValueError('Feedback selection is frozen; do not overwrite it')
    output.mkdir(parents=True)
    candidates = []
    common_hash, fit_ids = None, None
    inputs = {}
    for directory in args.directories:
        folder = Path(directory)
        features, rows, _, index = load_features(folder)
        positions = [i for i, r in enumerate(rows) if r['split'] in ('train', 'dev')]
        subset = [rows[i] for i in positions]
        identity = [(r['id'], r['split']) for r in subset]
        if common_hash is not None and (common_hash != index['dataset_sha256'] or identity != fit_ids):
            raise ValueError('Candidate datasets/partitions differ')
        common_hash, fit_ids = index['dataset_sha256'], identity
        encoder = folder.name
        candidates.extend(fit_candidates(features[positions], subset, encoder))
        inputs[encoder] = folder
        print('finished candidate grid', encoder, flush=True)
    ranking = rank_candidates(candidates)
    best = ranking[0]
    folder = inputs[best['encoder']]
    features, rows, _, _ = load_features(folder)
    train = np.array([r['split'] == 'train' for r in rows])
    labels = np.array([LABELS.index(r['actual_label']) for r in rows])
    x = feature_view(features, LAYERS.index(best['layer']), best['view'])
    model = fit_ridge(x[train], labels[train], best['regularization'])
    weights = output/'ridge-model.npz'
    np.savez_compressed(weights, **model)
    weights.chmod(0o600)
    selection = {'selected_at_utc': datetime.now(timezone.utc).isoformat(),
                 'selected': best, 'source_directory': str(folder),
                 'dataset_sha256': common_hash, 'weights_sha256': hashlib.sha256(weights.read_bytes()).hexdigest(),
                 'test_or_transfer_used_for_selection': False,
                 'train_ids': [r['id'] for r in rows if r['split'] == 'train'],
                 'dev_ids': [r['id'] for r in rows if r['split'] == 'dev'],
                 'limits': ['Exploratory re-selection on previously studied development data.',
                            'Zero observed development errors is not evidence of zero deployment risk.'],
                 'ranking': ranking}
    save_json(output/'selection.json', selection)
    print(json.dumps({k: best[k] for k in ['encoder', 'layer', 'view', 'regularization',
                                         'review_margin', 'matching_margin', 'development']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directories', nargs='+', required=True)
    parser.add_argument('--output', required=True)
    main(parser.parse_args())
