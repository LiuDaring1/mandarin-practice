"""Frozen Chinese-feature pair heads; all cohorts are already explored."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

import probe_hubert_fusion as parent
import probe_nasal_pairs as old_pairs
from nasal_feature_fusion import gate_scores
from nasal_pair_classifier import audit_training, pack_heads, pair_key, unpack_heads
from nasal_weighted_pairs import fit_heads, predict_heads
from train_nasal_feature_probe import save_json

engine = parent.engine
FOLDER = engine.BASE/'hubert-pairs-v1'


def checked():
    plan = json.loads((FOLDER/'plan.json').read_text())
    for path, digest in plan['sources'].items():
        if engine.sha(path) != digest:
            raise ValueError('Frozen pair source changed: '+path)
    return plan


def prepare():
    if FOLDER.exists():
        raise ValueError('Chinese pair experiment already frozen')
    prior = parent.checked(); old_pairs.checked()
    rows, _, available, _, _ = parent.load('existing', .25)
    support = audit_training([r for r in rows if r['split']=='train'])
    if support != prior['support'] or not available.all():
        raise ValueError('Training membership/support changed')
    paths = [Path(p) for p in prior['sources']]
    paths += [parent.FOLDER/n for n in ('plan.json','selection.json','evaluation.json')]
    paths += [old_pairs.FOLDER/n for n in ('plan.json','selection.json','evaluation.json')]
    paths += [Path('scripts')/n for n in ('nasal_weighted_pairs.py','probe_hubert_pairs.py','nasal_pair_classifier.py','probe_nasal_pairs.py')]
    plan = {'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'sources':{str(p):engine.sha(p) for p in paths}, 'support':support,
        'hubert_weights':[0.,.25,1.], 'regularizations':[.01,.1,1.], 'specialist_weights':[0.,.5,1.],
        'layers':{'xeus':19,'hubert':18}, 'candidate_count':27,
        'pooling':'unchanged original API vowel halves; fixed cached parent features',
        'specialist_other_class':'outside-family and nonnasal training speech',
        'shared_fallback_for_sparse_pairs':True, 'expected_direction_enters_classifier':False,
        'encoder_training':False, 'weak_labels_used':False, 'new_extraction':False,
        'calibration_mode':'directional', 'gate':'unchanged fixed Silero VAD', 'api_positive_veto':True,
        'ranking':['dev error detections','dev normal matches','shared tie preference','stronger regularization',
                   'lower specialist weight','Xeus tie preference','lower HuBERT weight'],
        'evaluate':['primary','best pair','best pair with Chinese features','best shared',
                    'shared at Chinese pair configuration','Xeus pair at Chinese pair configuration'],
        'shared_development_exact_replay_required':9, 'xeus_pair_development_exact_replay_required':9,
        'selection_splits':['train','dev'], 'evaluation_previously_explored':True,
        'new_api_requests':0, 'production_enabled':False,
        'limits':prior['limits']+['Family support is sparse and normal/error sources remain confounded.',
            'A specialist other class is not a diagnosis of a nonnasal realization.',
            'Head counterfactual invariance does not establish upstream reference-independent timing.']}
    FOLDER.mkdir(); save_json(FOLDER/'plan.json',plan)
    print('CHINESE PAIR PLAN FROZEN',plan['candidate_count'],support['eligible_pairs'],flush=True)


def rank(c):
    d = c['development']
    return (-d['correct_error_directions'],-d['correct_nasal_matches'],c['specialist_weight']!=0,
            -c['regularization'],c['specialist_weight'],c['hubert_weight']!=0,c['hubert_weight'])


def fit():
    from probe_phonetic_xeus import apply, calibrate
    from probe_nasal_boundaries import summarize_denominator
    plan = checked()
    if (FOLDER/'selection.json').exists() or list(FOLDER.glob('*-heads.npz')):
        raise ValueError('Chinese pair selection already frozen')
    shared = json.loads((parent.FOLDER/'selection.json').read_text())['ranking']
    old = json.loads((old_pairs.FOLDER/'selection.json').read_text())['ranking']
    models = {}; candidates = []; replay = {'shared':0,'xeus_pairs':0}
    for hw in plan['hubert_weights']:
        rows,x,available,present,dataset = parent.load('existing',hw)
        train = [i for i,r in enumerate(rows) if r['split']=='train']
        dev = [i for i,r in enumerate(rows) if r['split']=='dev']
        if not available[train+dev].all():
            raise ValueError('Changed train/dev availability')
        training = [rows[i] for i in train]; development = [rows[i] for i in dev]
        denominator = [r for r in dataset['rows']+dataset['excluded'] if r['split']=='dev']
        for strength in plan['regularizations']:
            heads = fit_heads(x[train],training,strength,plan['support'],hw)
            models[(hw,strength)] = heads
            for weight in plan['specialist_weights']:
                scores = predict_heads(heads,x[dev],[r['expected_final'] for r in development],weight,hw)
                scores = gate_scores(scores,present[dev])
                policy = calibrate(development,scores,plan['calibration_mode'])
                summary = summarize_denominator(denominator,apply(development,scores,policy))
                c = {**policy,'hubert_weight':hw,'regularization':strength,'specialist_weight':weight,'development':summary}
                if weight==0:
                    prior = next(v for v in shared if v['hubert_weight']==hw and v['regularization']==strength)
                    if any(json.dumps(c[k],sort_keys=True)!=json.dumps(prior[k],sort_keys=True) for k in c if k!='specialist_weight'):
                        raise ValueError('Shared development replay mismatch')
                    replay['shared'] += 1
                if hw==0:
                    prior = next(v for v in old if v['feature_source']=='xeus' and v['regularization']==strength and v['specialist_weight']==weight)
                    if any(json.dumps(c[k],sort_keys=True)!=json.dumps(prior[k],sort_keys=True) for k in c if k!='hubert_weight'):
                        raise ValueError('Xeus pair development replay mismatch')
                    replay['xeus_pairs'] += 1
                candidates.append(c)
                print('PAIR CANDIDATE',hw,strength,weight,summary['correct_error_directions'],summary['correct_nasal_matches'],flush=True)
    candidates.sort(key=rank)
    chinese = next(c for c in candidates if c['hubert_weight']>0 and c['specialist_weight']>0)
    selected = {'primary':candidates[0], 'pair':next(c for c in candidates if c['specialist_weight']>0),
        'chinese_pair':chinese, 'shared':next(c for c in candidates if c['specialist_weight']==0),
        'matched_shared':next(c for c in candidates if c['hubert_weight']==chinese['hubert_weight'] and c['regularization']==chinese['regularization'] and c['specialist_weight']==0),
        'matched_xeus_pair':next(c for c in candidates if c['hubert_weight']==0 and c['regularization']==chinese['regularization'] and c['specialist_weight']==chinese['specialist_weight'])}
    hashes = {}
    for name,c in selected.items():
        path = FOLDER/f'{name}-heads.npz'
        engine.save_npz(path,**pack_heads(models[(c['hubert_weight'],c['regularization'])])); hashes[name] = engine.sha(path)
    checked()
    save_json(FOLDER/'selection.json',{'plan_sha256':engine.sha(FOLDER/'plan.json'),'selected':selected,'ranking':candidates,
        'weights_sha256':hashes,'train_targets':len(train),'dev_targets':len(dev),'exact_development_replay':replay,
        'evaluation_used_for_selection':False})
    print('CHINESE PAIR SELECTED',json.dumps({n:{k:c[k] for k in ('hubert_weight','regularization','specialist_weight')} for n,c in selected.items()}),flush=True)


def evaluate():
    from probe_phonetic_xeus import apply, cohort_summary
    plan = checked(); output = FOLDER/'evaluation.json'
    if output.exists():
        raise ValueError('Chinese pair evaluation already frozen')
    selection = json.loads((FOLDER/'selection.json').read_text())
    if selection['plan_sha256']!=engine.sha(FOLDER/'plan.json'):
        raise ValueError('Selection provenance changed')
    previous_selection = json.loads((parent.FOLDER/'selection.json').read_text())['selected']
    previous_results = json.loads((parent.FOLDER/'evaluation.json').read_text())['comparison']
    comparison = {}; invariant = {}; noise = {}; replay = {}
    for name,c in selection['selected'].items():
        path = FOLDER/f'{name}-heads.npz'
        if engine.sha(path)!=selection['weights_sha256'][name]:
            raise ValueError('Frozen pair weights changed')
        with np.load(path,allow_pickle=False) as stored:
            heads = unpack_heads(dict(stored))
        comparison[name] = {}; invariant[name] = {}
        for cohort in ('existing','griffith','restored'):
            rows,x,available,present,dataset = parent.load(cohort,c['hubert_weight'])
            indices = [i for i,r in enumerate(rows) if available[i] and r['split'] not in ('train','dev') and r['expected_label']!='other']
            targets = [rows[i] for i in indices]; finals = [r['expected_final'] for r in targets]
            scores = predict_heads(heads,x[indices],finals,c['specialist_weight'],c['hubert_weight'])
            opposite = [pair_key(f) if f.endswith('ng') else pair_key(f)+'g' for f in finals]
            changed = predict_heads(heads,x[indices],opposite,c['specialist_weight'],c['hubert_weight'])
            if not np.array_equal(scores,changed):
                raise ValueError('Expected-direction leakage in pair scores')
            invariant[name][cohort] = {'targets':len(targets),'maximum_score_difference':0.,'features_and_bounds_unchanged':True}
            observations = apply(targets,gate_scores(scores,present[indices]),c)
            selected = {k:[r for r in dataset[k] if r['expected_label']!='other'] for k in ('rows','excluded')}
            values = cohort_summary(selected,observations)
            values['pairs'] = old_pairs.summarize_pairs(selected,observations,plan['support']['eligible_pairs'] if c['specialist_weight'] else [])
            comparison[name][cohort] = values
            if c['specialist_weight']==0:
                match = next((n for n,v in previous_selection.items() if all(c[k]==v[k] for k in ('hubert_weight','regularization'))),None)
                if match:
                    if observations!=previous_results[match][cohort]['predictions']:
                        raise ValueError('Shared evaluation replay mismatch')
                    replay[name+'-'+cohort] = len(observations)
            d = values['evaluation_only']
            print('PAIR EVALUATED',name,cohort,json.dumps({k:d[k] for k in ('correct_error_directions','false_nasal_accusations','false_reassurances','correct_nasal_matches','uncertain_nasal_targets')}),flush=True)
        rows,x,available,present,_ = parent.load('noise',c['hubert_weight'])
        if not available.all():raise ValueError('Incomplete background features')
        observations = []
        for final in ['an','ang','en','eng','ian','iang','in','ing','uan','uang']:
            scores = predict_heads(heads,x,[final]*len(x),c['specialist_weight'],c['hubert_weight'])
            targets = [{**r,'expected_final':final,'expected_label':'back' if final.endswith('ng') else 'front'} for r in rows]
            for state,s in [('gated',gate_scores(scores,present)),('ungated',scores)]:
                observations.extend({**o,'noise_source':r['noise_source'],'gate':state} for o,r in zip(apply(targets,s,c),rows))
        noise[name] = {'recordings':len(rows),'summaries':{state:{kind:{'conditions':len(part),
            'false_matches':sum(p['candidate_nasal_match'] for p in part),'false_corrections':sum(p['candidate_nasal_change'] for p in part),
            'abstentions':sum(not p['candidate_nasal_match'] and not p['candidate_nasal_change'] for p in part)}
            for kind in ('synthetic','recorded_environment') for part in [[p for p in observations if p['noise_source']==kind and p['gate']==state]]}
            for state in ('gated','ungated')}}
    checked()
    save_json(output,{'complete':True,'selection_sha256':engine.sha(FOLDER/'selection.json'),'comparison':comparison,
        'direction_invariance':invariant,'shared_prediction_exact_replay':replay,'noise':noise,'limits':plan['limits']})


if __name__=='__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode',choices=['prepare','fit','evaluate'])
    args = parser.parse_args(); {'prepare':prepare,'fit':fit,'evaluate':evaluate}[args.mode]()
