"""Train-only weak supervision with predeclared zero-weight matched controls."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import numpy as np

import probe_nasal_pairs as engine
import probe_nasal_source_balance as previous
from nasal_feature_probe import LABELS, predict_ridge
from nasal_feature_fusion import feature_source, gate_scores
from nasal_pair_classifier import pack_heads
from nasal_weak_supervision import audit_weak_rows, fit_weak_ridge, weak_weights
from train_nasal_feature_probe import save_json

FOLDER = engine.BASE/'weak-supervision-v1'
INVENTORY = engine.BASE/'eduhk-unmarked-inventory-v1'


@contextmanager
def experiment_root():
    old = engine.FOLDER
    engine.FOLDER = FOLDER
    try:
        yield
    finally:
        engine.FOLDER = old


def checked():
    with experiment_root():
        return engine.checked()


def prepare():
    if FOLDER.exists():
        raise ValueError('Weak experiment already frozen')
    parent = previous.checked()
    alignment = json.loads((INVENTORY/'alignment.json').read_text())
    if not alignment.get('complete') or alignment['plan_sha256'] != engine.sha(INVENTORY/'alignment-plan.json'):
        raise ValueError('Incomplete/stale weak alignment')
    for name in ('plan.json', 'alignment-plan.json'):
        for path, digest in json.loads((INVENTORY/name).read_text())['sources'].items():
            if engine.sha(path) != digest:
                raise ValueError('Weak source changed')
    for path, digest in alignment['cache_sources'].items():
        if engine.sha(path) != digest:
            raise ValueError('Weak alignment cache changed')
    rows, _, dataset = engine.load('existing')
    strong = [r for r in rows if r['split']=='train']
    audit = audit_weak_rows(strong, alignment['rows']+alignment['excluded'], rows+dataset['excluded'])
    paths = [Path(p) for p in parent['sources']]
    paths += [previous.FOLDER/name for name in ('plan.json', 'selection.json', 'evaluation.json')]
    paths += [INVENTORY/name for name in ('plan.json', 'inventory.json', 'alignment-plan.json', 'alignment.json')]
    paths += [engine.BASE/'xeus-v1'/name for name in ('model-source.json', 'runtime-source.json')]
    paths += [Path('scripts')/name for name in ('probe_nasal_weak.py', 'nasal_weak_supervision.py',
                'extract_weak_xeus.py', 'phonetic_xeus.py', 'zipa_context.py', 'nasal_acoustics.py')]
    hashes = {str(p): engine.sha(p) for p in paths}
    FOLDER.mkdir()
    shutil.copyfile(previous.FOLDER/'noise-features.npz', FOLDER/'noise-features.npz')
    (FOLDER/'noise-features.npz').chmod(0o600)
    hashes[str(FOLDER/'noise-features.npz')] = engine.sha(FOLDER/'noise-features.npz')
    plan = {key: parent[key] for key in ('support', 'calibration_mode', 'gate', 'api_positive_veto')}
    plan.update(frozen_at_utc=datetime.now(timezone.utc).isoformat(), sources=hashes,
        feature_sources=['xeus'], layer=19, view='trajectory', specialist_weights=[0.],
        regularizations=[.01, .1, 1.], weak_fractions=[0., .1, .25], weak_inventory_audit=audit,
        weak_rule='Each nasal class lends fraction of its fixed N_strong/3 loss mass to unverified expected targets.',
        total_loss_mass='N_strong, constant across all fractions; other class mass stays N_strong/3.',
        weak_inclusion='All locatable selected candidates, including API-flagged ones. No score filtering.',
        weak_usage='Training pseudo targets only; no actual_label assigned, no trusted dev/evaluation membership.',
        strong_labels='Original strong source audit unchanged; weak candidates audited separately.',
        selection_splits=['train', 'dev'], evaluation_previously_explored=True,
        ranking=['dev error detections', 'dev normal matches', 'smaller weak fraction', 'stronger regularization'],
        evaluate=['best overall', 'best positive weak fraction', 'best zero weight', 'zero at the best weak regularization'],
        encoder_training=False, reference_text_feature=False, noise_used_for_selection=False,
        production_enablement=False, anchor_feature_tolerance=1e-4)
    save_json(FOLDER/'plan.json', plan)
    save_json(FOLDER/'weak-dataset.json', {'rows': alignment['rows'], 'excluded': alignment['excluded'],
        'plan_sha256': engine.sha(FOLDER/'plan.json'), 'selected_targets': alignment['selected_targets'],
        'actual_labels_assigned': False})
    print('WEAK PLAN FROZEN', len(strong), 'strong train;', len(alignment['rows']), 'locatable weak;',
          len(alignment['excluded']), 'unavailable weak;', '9 candidates', flush=True)


def load_weak():
    plan = checked()
    dataset = json.loads((FOLDER/'weak-dataset.json').read_text())
    report = json.loads((FOLDER/'feature-report.json').read_text())
    if (dataset['plan_sha256'] != engine.sha(FOLDER/'plan.json') or not report.get('complete')
            or report['plan_sha256'] != engine.sha(FOLDER/'plan.json')
            or report['dataset_sha256'] != engine.sha(FOLDER/'weak-dataset.json')
            or report['features_sha256'] != engine.sha(FOLDER/'weak-features.npz')
            or report['layer'] != plan['layer'] or report['view'] != plan['view']):
        raise ValueError('Incomplete/stale weak features')
    lookup = {r['id']: r for r in dataset['rows']}
    with np.load(FOLDER/'weak-features.npz', allow_pickle=False) as values:
        ids = values['ids'].tolist(); x = values['features']
    if len(ids) != len(set(ids)) or set(ids) | {r['id'] for r in report['excluded']} != set(lookup):
        raise ValueError('Weak feature denominator changed')
    return [lookup[uid] for uid in ids], x, dataset


def same_serialized_policy(first, second):
    # JSON persists tuple metadata as lists; compare exact canonical contents.
    return json.dumps(first, sort_keys=True, allow_nan=False) == json.dumps(second, sort_keys=True, allow_nan=False)


def fit():
    from probe_nasal_boundaries import summarize_denominator
    from probe_phonetic_xeus import apply, calibrate
    plan = checked()
    if (FOLDER/'selection.json').exists() or list(FOLDER.glob('*-heads.npz')):
        raise ValueError('Weak selection already frozen')
    rows, x, dataset = engine.load('existing')
    train = [i for i, r in enumerate(rows) if r['split']=='train']
    dev = [i for i, r in enumerate(rows) if r['split']=='dev']
    strong = [rows[i] for i in train]; development = [rows[i] for i in dev]
    x = feature_source(x, 'xeus')
    weak_rows, weak_x, _ = load_weak()
    weak_audit = audit_weak_rows(strong, weak_rows, rows+dataset['excluded'])
    labels = np.array([LABELS.index(r['actual_label']) for r in strong])
    pseudo = np.array([LABELS.index(r['expected_label']) for r in weak_rows])
    denominator = [r for r in dataset['rows']+dataset['excluded'] if r['split']=='dev']
    acceptance = engine.present(development, 'existing')
    old = json.loads((previous.FOLDER/'selection.json').read_text())['ranking']
    candidates = []; models = {}; audits = {}
    for fraction in plan['weak_fractions']:
        audits[str(fraction)] = weak_weights(labels, pseudo, fraction)[2]
        for strength in plan['regularizations']:
            head = fit_weak_ridge(x[train], labels, weak_x, pseudo, fraction, strength)
            models[(fraction, strength)] = head
            scores = gate_scores(predict_ridge(head, x[dev]), acceptance)
            policy = calibrate(development, scores, plan['calibration_mode'])
            candidate = {**policy, 'feature_source': 'xeus', 'regularization': strength, 'specialist_weight': 0.,
                'development': summarize_denominator(denominator, apply(development, scores, policy))}
            if fraction == 0:
                prior = next(c for c in old if c['weighting']=='class_only' and c['feature_source']=='xeus'
                             and c['regularization']==strength and c['specialist_weight']==0)
                if not same_serialized_policy(candidate, {k: v for k, v in prior.items() if k!='weighting'}):
                    raise ValueError('Zero weight failed exact development replay')
            candidate['weak_fraction'] = fraction
            candidates.append(candidate)
            d = candidate['development']
            print('WEAK CANDIDATE', fraction, strength, d['correct_error_directions'], d['correct_nasal_matches'], flush=True)
    candidates.sort(key=lambda c: (-c['development']['correct_error_directions'],
        -c['development']['correct_nasal_matches'], c['weak_fraction'], -c['regularization']))
    best = next(c for c in candidates if c['weak_fraction']>0)
    selected = {'primary': candidates[0], 'weak': best,
        'zero': next(c for c in candidates if c['weak_fraction']==0),
        'matched_control': next(c for c in candidates if c['weak_fraction']==0 and c['regularization']==best['regularization'])}
    hashes = {}
    for name, c in selected.items():
        path = FOLDER/f'{name}-heads.npz'
        engine.save_npz(path, **pack_heads({'shared': models[(c['weak_fraction'], c['regularization'])]}))
        hashes[name] = engine.sha(path)
    save_json(FOLDER/'selection.json', {'selected': selected, 'ranking': candidates, 'weights_sha256': hashes,
        'plan_sha256': engine.sha(FOLDER/'plan.json'), 'feature_report_sha256': engine.sha(FOLDER/'feature-report.json'),
        'selected_at_utc': datetime.now(timezone.utc).isoformat(), 'train_ids': [r['id'] for r in strong],
        'weak_train_ids': [r['id'] for r in weak_rows], 'dev_ids': [r['id'] for r in development],
        'weak_audit': weak_audit, 'weight_audits': audits, 'zero_weight_development_exact_replay': 3,
        'weak_targets_used_as_gold': False, 'evaluation_rows_used_for_selection': False, 'noise_used_for_selection': False})
    print('WEAK SELECTED', json.dumps({name: {k: c[k] for k in ('weak_fraction', 'regularization')}
                                     for name, c in selected.items()}), flush=True)


def evaluate():
    checked(); load_weak()
    selection = json.loads((FOLDER/'selection.json').read_text())
    if selection['feature_report_sha256'] != engine.sha(FOLDER/'feature-report.json'):
        raise ValueError('Feature report changed after selection')
    with experiment_root():
        engine.evaluate()


if __name__=='__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['prepare', 'fit', 'evaluate'])
    args = parser.parse_args(); {'prepare': prepare, 'fit': fit, 'evaluate': evaluate}[args.mode]()
