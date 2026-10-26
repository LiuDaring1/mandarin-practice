"""Freeze a nonlinear acoustic-head comparison; reuse all existing data/gates."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import numpy as np

import probe_nasal_pairs as engine
import probe_nasal_weak as previous
from nasal_feature_fusion import feature_source, gate_scores
from nasal_feature_probe import LABELS, fit_ridge, predict_ridge
from nasal_kernel_classifier import fit_kernel, predict_kernel
from nasal_pair_classifier import audit_training
from train_nasal_feature_probe import save_json

FOLDER = engine.BASE/'kernel-classifier-v1'


def checked():
    plan = json.loads((FOLDER/'plan.json').read_text())
    for path, digest in plan['sources'].items():
        if engine.sha(path) != digest:
            raise ValueError('Frozen kernel source changed: '+path)
    return plan


def prepare():
    if FOLDER.exists():
        raise ValueError('Kernel experiment already frozen')
    parent = previous.checked()
    rows, _, dataset = engine.load('existing')
    strong = [r for r in rows if r['split']=='train']
    support = audit_training(strong)
    if support != parent['support']:
        raise ValueError('Strong training audit changed')
    paths = [Path(p) for p in parent['sources']]
    paths += [previous.FOLDER/name for name in ('plan.json', 'implementation-amendment.json', 'selection.json', 'evaluation.json')]
    paths += [Path(__file__), Path('scripts/nasal_kernel_classifier.py')]
    hashes = {str(p): engine.sha(p) for p in paths}
    FOLDER.mkdir()
    shutil.copyfile(previous.FOLDER/'noise-features.npz', FOLDER/'noise-features.npz')
    (FOLDER/'noise-features.npz').chmod(0o600)
    hashes[str(FOLDER/'noise-features.npz')] = engine.sha(FOLDER/'noise-features.npz')
    plan = {key: parent[key] for key in ('support', 'calibration_mode', 'gate', 'api_positive_veto')}
    plan.update(frozen_at_utc=datetime.now(timezone.utc).isoformat(), sources=hashes,
        feature_source='xeus', layer=19, view='trajectory', kinds=['linear', 'rbf'],
        regularizations=[.01, .1, 1.], bandwidth_multipliers=[.25, 1., 4.],
        bandwidth_rule='gamma=1/(2*multiplier*median(positive off-diagonal squared training distances))',
        normalization='Same class-balanced training mean/scale and sqrt(dimension) as original linear model.',
        centering='RBF kernel and targets centered with training class mass; intercept fitted without penalty.',
        training_targets=len(strong), weak_targets_used=False, encoder_training=False,
        reference_text_feature=False, source_identity_feature=False,
        selection_splits=['train', 'dev'], evaluation_previously_explored=True,
        ranking=['dev error detections', 'dev normal matches', 'linear tie preference', 'stronger ridge', 'larger bandwidth'],
        evaluate=['best overall', 'best RBF', 'best linear', 'linear with best RBF ridge strength'],
        noise_used_for_selection=False, production_enablement=False)
    save_json(FOLDER/'plan.json', plan)
    print('KERNEL PLAN FROZEN', len(strong), 'strong train targets; 3 linear + 9 RBF candidates', flush=True)


def predict(model, features, kind):
    if kind == 'linear':
        return predict_ridge(model, features)
    if kind == 'rbf':
        return predict_kernel(model, features)
    raise ValueError('Unknown classifier kind')


def rank(candidate):
    return (-candidate['development']['correct_error_directions'],
            -candidate['development']['correct_nasal_matches'], candidate['kind']!='linear',
            -candidate['regularization'], -candidate['bandwidth_multiplier'])


def fit():
    from probe_nasal_boundaries import summarize_denominator
    from probe_phonetic_xeus import apply, calibrate
    plan = checked()
    if (FOLDER/'selection.json').exists() or list(FOLDER.glob('*-model.npz')):
        raise ValueError('Kernel selection already frozen')
    rows, paired, dataset = engine.load('existing')
    train = [i for i,r in enumerate(rows) if r['split']=='train']; dev = [i for i,r in enumerate(rows) if r['split']=='dev']
    strong = [rows[i] for i in train]; development = [rows[i] for i in dev]
    if audit_training(strong) != plan['support']:
        raise ValueError('Training labels changed')
    x = feature_source(paired, plan['feature_source'])
    labels = np.array([LABELS.index(r['actual_label']) for r in strong])
    denominator = [r for r in dataset['rows']+dataset['excluded'] if r['split']=='dev']
    acceptance = engine.present(development, 'existing')
    old = json.loads((previous.FOLDER/'selection.json').read_text())['ranking']
    models = {}; candidates = []
    for kind in plan['kinds']:
        for bandwidth in ([0.] if kind=='linear' else plan['bandwidth_multipliers']):
            for strength in plan['regularizations']:
                model = (fit_ridge(x[train], labels, strength) if kind=='linear'
                         else fit_kernel(x[train], strong, strength, bandwidth))
                models[(kind, bandwidth, strength)] = model
                scores = gate_scores(predict(model, x[dev], kind), acceptance)
                policy = calibrate(development, scores, plan['calibration_mode'])
                base = {**policy, 'feature_source': plan['feature_source'], 'regularization': strength,
                        'specialist_weight': 0.,
                        'development': summarize_denominator(denominator, apply(development, scores, policy))}
                if kind=='linear':
                    prior = next(c for c in old if c['weak_fraction']==0 and c['regularization']==strength)
                    if not previous.same_serialized_policy(base, {k:v for k,v in prior.items() if k!='weak_fraction'}):
                        raise ValueError('Linear candidate failed exact development replay')
                c = {**base, 'kind': kind, 'bandwidth_multiplier': bandwidth}
                if kind=='rbf':
                    c['median_training_distance'] = float(model['median_training_distance'])
                    c['gamma'] = float(model['gamma'])
                candidates.append(c)
                print('KERNEL CANDIDATE', kind, bandwidth, strength,
                      c['development']['correct_error_directions'], c['development']['correct_nasal_matches'], flush=True)
    candidates.sort(key=rank)
    kernel = next(c for c in candidates if c['kind']=='rbf')
    selected = {'primary': candidates[0], 'kernel': kernel,
        'linear': next(c for c in candidates if c['kind']=='linear'),
        'matched_control': next(c for c in candidates if c['kind']=='linear' and c['regularization']==kernel['regularization'])}
    hashes = {}
    for name,c in selected.items():
        path = FOLDER/f'{name}-model.npz'
        engine.save_npz(path, **models[(c['kind'], c['bandwidth_multiplier'], c['regularization'])])
        hashes[name] = engine.sha(path)
    save_json(FOLDER/'selection.json', {'plan_sha256': engine.sha(FOLDER/'plan.json'), 'selected': selected,
        'ranking': candidates, 'weights_sha256': hashes, 'selected_at_utc': datetime.now(timezone.utc).isoformat(),
        'train_ids': [r['id'] for r in strong], 'dev_ids': [r['id'] for r in development],
        'linear_development_exact_replay': 3, 'weak_targets_used': False,
        'evaluation_rows_used_for_selection': False, 'noise_used_for_selection': False})
    print('KERNEL SELECTED', json.dumps({n:{k:c[k] for k in ('kind','bandwidth_multiplier','regularization')}
                                       for n,c in selected.items()}), flush=True)


def evaluate():
    from probe_phonetic_xeus import apply, cohort_summary
    plan = checked()
    if (FOLDER/'evaluation.json').exists():
        raise ValueError('Kernel evaluation already frozen')
    selection = json.loads((FOLDER/'selection.json').read_text())
    if selection['plan_sha256'] != engine.sha(FOLDER/'plan.json'):
        raise ValueError('Kernel plan changed')
    reports = {}; noise = {}; invariance = {}; replay = {}
    previous_reports = json.loads((previous.FOLDER/'evaluation.json').read_text())['comparison']['primary']
    for name,candidate in selection['selected'].items():
        path = FOLDER/f'{name}-model.npz'
        if engine.sha(path) != selection['weights_sha256'][name]:
            raise ValueError('Classifier weights changed')
        with np.load(path, allow_pickle=False) as stored:
            model = dict(stored)
        reports[name] = {}; invariance[name] = {}
        for cohort in ('existing', 'griffith'):
            rows, paired, dataset = engine.load(cohort)
            positions = [i for i,r in enumerate(rows) if r['split'] not in ('train','dev') and r['expected_label']!='other']
            rows = [rows[i] for i in positions]; x = feature_source(paired[positions], candidate['feature_source'])
            scores = predict(model, x, candidate['kind'])
            # Inference has no metadata argument. Counterfactual targets change
            # only the interpretation of a fixed acoustic prediction below.
            alternate = [{**r, 'expected_label': 'back' if r['expected_label']=='front' else 'front'} for r in rows]
            counterfactual = predict(model, x, candidate['kind'])
            if not np.array_equal(scores, counterfactual) or any(a['expected_label']==b['expected_label'] for a,b in zip(rows,alternate)):
                raise ValueError('Acoustic-only prediction invariance failed')
            invariance[name][cohort] = {'targets':len(rows),'maximum_score_difference':float(np.max(np.abs(scores-counterfactual))),
                                      'prediction_accepts_target_metadata':False, 'features_and_bounds_unchanged':True}
            observed = apply(rows, gate_scores(scores, engine.present(rows,cohort)), candidate)
            selected = {k:[r for r in dataset[k] if r['expected_label']!='other'] for k in ('rows','excluded')}
            summary = cohort_summary(selected, observed)
            summary['pairs'] = engine.summarize_pairs(selected, observed, [])
            reports[name][cohort] = summary
            if name=='linear':
                if observed != previous_reports[cohort]['predictions']:
                    raise ValueError('Original linear evaluation failed exact replay')
                replay[cohort] = {'targets':len(observed),'all_prediction_fields_identical':True}
            d = summary['evaluation_only']
            print('KERNEL EVALUATED', name, cohort, json.dumps({k:d[k] for k in ('correct_error_directions','known_nasal_errors',
                'false_nasal_accusations','correct_nasal_targets','false_reassurances','correct_nasal_matches','uncertain_nasal_targets')}), flush=True)
        noise_rows = json.loads((engine.SOURCE/'noise/dataset.json').read_text())['rows']
        with np.load(FOLDER/'noise-features.npz',allow_pickle=False) as stored:
            if stored['ids'].tolist() != [r['id'] for r in noise_rows]:
                raise ValueError('Noise feature identity changed')
            x = feature_source(stored['features'], candidate['feature_source'])
        finals = [f for key in plan['support']['eligible_pairs']+['uan'] for f in (key,key+'g')]
        evidence = json.loads((engine.SOURCE/'evidence.json').read_text())['cohorts']['noise']
        accept = np.array([evidence[r['id']]['present'] for r in noise_rows],dtype=bool)
        scores = predict(model,x,candidate['kind']); observations=[]
        for final in finals:
            targets = [{**r,'expected_final':final,'expected_label':'back' if final.endswith('ng') else 'front'} for r in noise_rows]
            for state,values in [('gated',gate_scores(scores,accept)),('ungated',scores)]:
                observations.extend({**o,'gate':state,'expected_final':final,'noise_source':r['noise_source']}
                                    for o,r in zip(apply(targets,values,candidate),noise_rows))
        noise[name] = {'recordings':len(noise_rows),'tested_reference_finals':finals,
            'summaries':{kind:{state:{'conditions':len(part),
                'false_matches':sum(r['candidate_nasal_match'] for r in part),
                'false_corrections':sum(r['candidate_nasal_change'] for r in part),
                'abstentions':sum(not r['candidate_nasal_match'] and not r['candidate_nasal_change'] for r in part)}
                for state in ('gated','ungated') for part in [[r for r in observations if r['noise_source']==kind and r['gate']==state]]}
                for kind in ('synthetic','recorded_environment')},'predictions':observations}
    save_json(FOLDER/'evaluation.json', {'complete':True,'selection_sha256':engine.sha(FOLDER/'selection.json'),
        'selected':selection['selected'],'comparison':reports,'noise':noise,'counterfactual_invariance':invariance,
        'original_linear_replay':replay,'limits':['Explored comparison sets, not new blind acceptance.',
        'No noisy speech, omission, repetition, real microphone or production feedback validation.',
        'Kernel scores and gaps are not probabilities.', 'Unchanged reference-dependent API bounds remain a limitation.']})
    print('KERNEL EVALUATION COMPLETE',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','fit','evaluate'])
    args=parser.parse_args();{'prepare':prepare,'fit':fit,'evaluate':evaluate}[args.mode]()
