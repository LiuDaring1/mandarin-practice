"""Prospective n/ng specificity controls; other segment errors stay errors.

Two API stages freeze exact requests before execution. Neither annotations nor
thresholds are changed by outcomes. Private data never enters production.
"""
import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

import probe_ise_pinyin_pairs as paired
from ise_probe import IseProbe, public_result, target_at
from prepare_nasal_feature_data import interval
from probe_ise_pinyin_challenge import dictionary_bodies, dictionary_identity, merged_decision
from resume_ise_pinyin_pairs import input_failure
from suntone_probe import private_json

BASE = paired.BASE
INPUT = BASE/'same-tail-controls-v1'
FOLDER = BASE/'same-tail-specificity-v1'
TEMPORAL = BASE/'hubert-temporal-v1'
MODES = ('api', 'local', 'agreement', 'correction_union')


def read(path):
    return json.loads(Path(path).read_text())


def validate_controls(records):
    ids = set()
    for rec in records:
        if rec['split'] != 'external' or not rec['targets']:
            raise ValueError('Controls must remain evaluation-only')
        for target in rec['targets']:
            uid = rec['uid']+'-pos'+str(target['position'])
            if uid in ids:
                raise ValueError('Duplicate target identity')
            ids.add(uid)
            if (target['state'] != 'same_tail_segmental_error' or
                    target['label_source'] != 'explicit_suffix_same_nasal_class' or
                    target['actual_label'] != target['expected_label'] or
                    target['actual_label'] not in ('front', 'back') or
                    target['whole_pronunciation_correct'] is not False or
                    target['evaluation_only'] is not True):
                raise ValueError('Not an annotated same-tail segmental error')
    return ids


def stage_budget(requests, ledger, cache_dir):
    unique = {}
    for r in requests:
        if r['key'] in unique and any(unique[r['key']][k] != r[k] for k in ('audio', 'reference', 'core')):
            # Different paths may hold the same bytes, but this batch has no
            # such aliases; reject silently conflating request metadata.
            raise ValueError('Conflicting request identity')
        unique[r['key']] = r
    existing = {}; new = []
    for key in sorted(unique):
        path = cache_dir/(key+'.json')
        if path.exists(): existing[str(path)] = paired.sha(path)
        elif key in ledger: raise ValueError('Reserved request missing result; no retry')
        else: new.append(key)
    if len(new) > 100: raise ValueError('Batch exceeds request allowance')
    return {'requests': [unique[k] for k in sorted(unique)], 'ledger_prefix': ledger,
            'new_request_keys': new, 'existing_caches': existing,
            'maximum_additional_attempts': len(new), 'maximum_total_attempts': len(ledger)+len(new)}


def checked():
    plan = read(FOLDER/'plan.json')
    for p, digest in plan['sources'].items():
        if paired.sha(p) != digest: raise ValueError('Frozen specificity source changed: '+p)
    if dictionary_identity() != plan['dictionary']: raise ValueError('Pinyin dictionary changed')
    validate_controls(read(INPUT/'input.json')['records'])
    return plan


def prepare():
    if FOLDER.exists(): raise ValueError('Specificity plan already frozen')
    from probe_hubert_temporal import checked as temporal_checked
    parent = temporal_checked(); manifest = read(INPUT/'input.json')
    for p, digest in read(INPUT/'plan.json')['sources'].items():
        if paired.sha(p) != digest: raise ValueError('Control inventory source changed')
    if manifest['plan_sha256'] != paired.sha(INPUT/'plan.json'): raise ValueError('Inventory plan changed')
    if len(validate_controls(manifest['records'])) != 24: raise ValueError('Expected all 24 controls')
    selection = read(TEMPORAL/'selection.json'); policy = selection['selected']['primary']
    if policy['view'] != 'resampled4' or policy['regularization'] != .1:
        raise ValueError('Unexpected previously selected model')
    weights = TEMPORAL/'primary-model.npz'
    if paired.sha(weights) != selection['weights_sha256']['primary']: raise ValueError('Model weights changed')
    original = read(BASE/'griffith-external-v2/dataset.json')
    with np.load(TEMPORAL/'griffith-features.npz', allow_pickle=False) as values:
        available = set(values['ids'].tolist())
    replay = []; audios = set()
    for row in sorted(original['rows'], key=lambda r:r['id']):
        if row['id'] in available and row['audio'] not in audios:
            replay.append(row); audios.add(row['audio'])
        if len(replay) == 3: break
    if len(replay) != 3: raise ValueError('Missing baseline feature replay targets')
    paths = [INPUT/'plan.json', INPUT/'input.json', weights, Path(__file__),
        BASE/'griffith-external-v2/dataset.json']
    paths += [TEMPORAL/n for n in ('plan.json','selection.json','feature-report.json','griffith-features.npz')]
    paths += [Path('scripts')/n for n in ('probe_ise_pinyin_challenge.py','probe_ise_pinyin_pairs.py',
        'resume_ise_pinyin_pairs.py','prepare_nasal_feature_data.py','ise_interphonic_preflight.py',
        'ise_probe.py','suntone_probe.py','chinese_hubert_features.py','hubert_temporal_features.py',
        'silero_nasal_gate.py','nasal_feature_probe.py','nasal_feature_fusion.py','probe_phonetic_xeus.py',
        'nasal_directional_calibration.py','fit_nasal_context_probe.py','zipa_context.py')]
    for rec in manifest['records']:
        if paired.sha(rec['audio']) != rec['audio_sha256']: raise ValueError('Control audio changed')
        paths.append(Path(rec['audio']))
    requests = [{'audio':r['audio'], 'reference':r['reference'], 'core':r['core'],
                 'key':paired.cache_key(r['audio'],r['reference'],r['core'])} for r in manifest['records']]
    ledger = read(paired.PROVIDER/'requests.json')
    if len(ledger) != 497: raise ValueError('Expected ledger start 497')
    budget = stage_budget(requests, ledger, paired.PROVIDER/'cache')
    FOLDER.mkdir()
    private_json(FOLDER/'plan.json', {'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'sources':{**parent['sources'], **{str(p):paired.sha(p) for p in paths}},
        'dictionary':dictionary_identity(), 'model':parent['model'], 'policy':policy,
        'weights':str(weights), 'layer':18, 'view':'resampled4', 'baseline_replay':replay,
        'baseline_tolerance':1e-4, 'selected_targets':24, 'recordings':19,
        'comparison_modes':list(MODES), 'new_fit_or_calibration':False, 'production_enabled':False,
        'human_bounds_for_inference':False,
        'pair_overlap_rule':'At least 50% of the shorter API syllable shared between the two API reference conditions; NOT overlap with human bounds.',
        'whole_word_correctness_assessed':False,
        'failure_policy':'48195/60114 retained unavailable; other failures stop; failed/reserved identities never retried.',
        'api_stages':'Plain exact keys frozen now. Paired exact keys frozen after plain results, before new paired requests.',
        'evaluation_only':True, 'same_explored_corpus':True})
    private_json(FOLDER/'plain-plan.json', {**budget,'main_plan_sha256':paired.sha(FOLDER/'plan.json')})
    print('SPECIFICITY FROZEN 24 targets; plain new', len(budget['new_request_keys']),
          'cap',budget['maximum_total_attempts'],flush=True)


def checked_stage(name):
    checked(); plan = read(FOLDER/(name+'-plan.json'))
    if plan['main_plan_sha256'] != paired.sha(FOLDER/'plan.json'): raise ValueError('Main plan changed')
    for p,digest in plan['existing_caches'].items():
        if paired.sha(p) != digest: raise ValueError('Original cache changed')
    for r in plan['requests']:
        if paired.cache_key(r['audio'],r['reference'],r['core']) != r['key']:
            raise ValueError('Stage request identity changed')
    if name == 'pairs' and plan['plain_result_sha256'] != paired.sha(FOLDER/'plain-result.json'):
        raise ValueError('Plain result changed')
    return plan


async def run_stage(name, allow_paid=False):
    plan = checked_stage(name); output = FOLDER/(name+'-result.json')
    if output.exists(): raise ValueError('Stage result already frozen')
    paired.check_ledger(plan['ledger_prefix'],read(paired.PROVIDER/'requests.json'),plan['new_request_keys'])
    probe = IseProbe(paired.PROVIDER, allow_paid=allow_paid,max_calls=plan['maximum_total_attempts'])
    results = {}
    for i,r in enumerate(plan['requests']):
        result = public_result(await probe.call(r['audio'],r['reference'],core=r['core']))
        path = paired.PROVIDER/'cache'/(r['key']+'.json')
        results[r['key']] = {'result':result,'cache_sha256':paired.sha(path)}
        private_json(FOLDER/(name+'-progress.json'),{'results':results})
        if result['status'] != 'ok' and not input_failure(result):
            private_json(FOLDER/(name+'-failure.json'),{'key':r['key'],'result':result})
            raise RuntimeError('Unclassified API failure; stopped without retry')
        print('SPECIFICITY API',name,i+1,'/',len(plan['requests']),result['status'],flush=True)
    checked_stage(name); ledger = read(paired.PROVIDER/'requests.json')
    added = paired.check_ledger(plan['ledger_prefix'],ledger,plan['new_request_keys'])
    private_json(output,{'complete':True,'stage_plan_sha256':paired.sha(FOLDER/(name+'-plan.json')),
        'results':results,'additional_attempts':added,'total_attempts':len(ledger),
        'failed_requests':sum(v['result']['status']!='ok' for v in results.values())})
    print('SPECIFICITY API COMPLETE',name,'added',added,'total',len(ledger),flush=True)


def read_stage_result(name):
    checked_stage(name); result = read(FOLDER/(name+'-result.json'))
    if not result['complete'] or result['stage_plan_sha256'] != paired.sha(FOLDER/(name+'-plan.json')):
        raise ValueError('Stage result provenance changed')
    for key,value in result['results'].items():
        if paired.sha(paired.PROVIDER/'cache'/(key+'.json')) != value['cache_sha256']:
            raise ValueError('Response cache changed')
    return result


def prepare_pairs():
    checked(); output = FOLDER/'pairs-plan.json'
    if output.exists(): raise ValueError('Paired request plan already frozen')
    source = read_stage_result('plain'); rows = []; excluded = []; pairs = []; requests = []
    vocabulary = set(dictionary_bodies())
    for rec in read(INPUT/'input.json')['records']:
        key = paired.cache_key(rec['audio'],rec['reference'],rec['core'])
        result = source['results'][key]['result']
        for target in rec['targets']:
            row = {**target,**{k:rec[k] for k in ('audio','speaker','split','reference','core','audio_sha256')},
                'id':rec['uid']+'-pos'+str(target['position']),'condition':'same_tail_segmental_error'}
            observation = target_at(result,rec['reference'],target['position'])
            row['api_state'] = observation['state']; bounds = interval(observation,rec['audio'])
            if bounds is None: excluded.append({**row,'reason':'unusable_plain_interval'})
            else: rows.append({**row,'bounds':bounds})
            record = {**row,'conditions':[]}
            try:
                text,symbols = paired.reference_symbols(result,rec['reference'])
                if symbols[target['position']] != target['nominal_pinyin']:
                    raise ValueError('Reference pinyin differs from published nominal reading')
                other = symbols.copy(); other[target['position']] = paired.opposite_pinyin(other[target['position']])
                if any(v[:-1] not in vocabulary for v in symbols+other):
                    raise ValueError('Reference contains a syllable absent from the pinned basic-Han dictionary')
                for name,values in [('expected',symbols),('opposite',other)]:
                    reference = paired.interphonic_word(text,values)
                    request = {'audio':rec['audio'],'core':rec['core'],'reference':reference,
                               'key':paired.cache_key(rec['audio'],reference,rec['core'])}
                    requests.append(request); record['conditions'].append({**request,'name':name,'pinyin':values})
            except ValueError as error: record['preparation_failure'] = str(error)
            pairs.append(record)
    if len(rows)+len(excluded) != 24 or len(pairs) != 24: raise ValueError('Lost control denominator')
    budget = stage_budget(requests,read(paired.PROVIDER/'requests.json'),paired.PROVIDER/'cache')
    private_json(FOLDER/'dataset.json',{'rows':rows,'excluded':excluded,'evaluation_only':True,
        'plain_result_sha256':paired.sha(FOLDER/'plain-result.json'),'whole_word_correctness_assessed':False})
    private_json(output,{**budget,'rows':pairs,'main_plan_sha256':paired.sha(FOLDER/'plan.json'),
        'plain_result_sha256':paired.sha(FOLDER/'plain-result.json'),'dataset_sha256':paired.sha(FOLDER/'dataset.json')})
    print('SPECIFICITY PAIRED FROZEN prepared',sum(bool(r['conditions']) for r in pairs),
          'new',len(budget['new_request_keys']),'cap',budget['maximum_total_attempts'],
          'local usable',len(rows),'unavailable',len(excluded),flush=True)


def dataset_checked():
    plan = checked_stage('pairs')
    if paired.sha(FOLDER/'dataset.json') != plan['dataset_sha256']: raise ValueError('Target dataset changed')
    data = read(FOLDER/'dataset.json')
    expected = validate_controls(read(INPUT/'input.json')['records'])
    rows = data['rows']+data['excluded']
    if len(rows) != len(expected) or {r['id'] for r in rows} != expected:
        raise ValueError('Control denominator changed')
    return data


def extract():
    from chinese_hubert_features import ChineseHubert, LAYERS
    from hubert_temporal_features import pool_views
    from nasal_acoustics import read_audio
    from silero_nasal_gate import SileroGate, target_speech
    from zipa_context import context_interval
    from probe_nasal_pairs import save_npz
    plan = checked(); dataset = dataset_checked(); output = FOLDER/'feature-report.json'
    if output.exists(): raise ValueError('Specificity features already frozen')
    model = ChineseHubert(); gate = SileroGate()
    if model.identity != plan['model']: raise ValueError('Frozen CPU runtime changed')
    with np.load(TEMPORAL/'griffith-features.npz',allow_pickle=False) as old:
        previous = {uid:old['resampled4'][i] for i,uid in enumerate(old['ids'].tolist())}
    vectors = {}; present = {}; errors = []; replays = []; caches = {}; cache = FOLDER/'feature-cache'
    cache.mkdir(exist_ok=True)
    for stage,members in [('replay',plan['baseline_replay']),('controls',dataset['rows'])]:
        grouped = defaultdict(list)
        for row in members: grouped[row['audio']].append(row)
        for audio,rows in grouped.items():
            if any(paired.sha(audio) != r['audio_sha256'] for r in rows): raise ValueError('Inference audio changed')
            samples = read_audio(Path(audio),max_seconds=60); vad = gate.score(samples); parents = defaultdict(list)
            for row in rows:
                try: parents[context_interval(len(samples),row['bounds']['syllable'])].append(row)
                except ValueError as error:
                    if stage == 'replay': raise
                    errors.append({'id':row['id'],'reason':str(error)})
            for (a,b),targets in parents.items():
                identity = {'main_plan_sha256':paired.sha(FOLDER/'plan.json'),
                    'dataset_sha256':paired.sha(FOLDER/'dataset.json'),'audio_sha256':paired.sha(audio),
                    'stage':stage,'window':[a,b],'targets':[[r['id'],r['bounds']] for r in targets]}
                key = hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
                path = cache/(key+'.npz'); meta = cache/(key+'.json')
                if not (path.exists() and meta.exists()):
                    states = model.infer(samples[a:b])[LAYERS.index(18)]; ids = []; values = []; failed = []
                    for row in targets:
                        try: views,count = pool_views(states,row['bounds'],a,b-a,model.stride,model.field)
                        except ValueError as error:
                            if stage == 'replay': raise
                            failed.append({'id':row['id'],'reason':str(error)}); continue
                        ids.append(row['id']); values.append(views['resampled4'])
                    save_npz(path,ids=np.array(ids),values=np.array(values,dtype=np.float32).reshape(-1,4096))
                    private_json(meta,{'identity':identity,'sha256':paired.sha(path),'unavailable':failed})
                    del states
                info = read(meta)
                if info['identity'] != identity or info['sha256'] != paired.sha(path): raise ValueError('Feature cache changed')
                with np.load(path,allow_pickle=False) as stored:
                    lookup = {r['id']:r for r in targets}
                    for i,uid in enumerate(stored['ids'].tolist()):
                        if stage == 'replay':
                            delta = float(np.max(np.abs(stored['values'][i]-previous[uid])))
                            if delta > plan['baseline_tolerance']: raise ValueError('Temporal replay failed')
                            replays.append({'id':uid,'maximum_difference':delta})
                        else:
                            if uid in vectors: raise ValueError('Duplicate feature')
                            vectors[uid] = stored['values'][i]
                            present[uid] = target_speech(vad,len(samples),lookup[uid]['bounds'])
                errors.extend(info['unavailable']); caches[str(path)] = paired.sha(path); caches[str(meta)] = paired.sha(meta)
            print('SPECIFICITY FEATURES',stage,'replay',len(replays),'controls',len(vectors),'unavailable',len(errors),flush=True)
    ids = [r['id'] for r in dataset['rows'] if r['id'] in vectors]
    if len(replays) != 3 or len(ids)+len(errors) != len(dataset['rows']): raise ValueError('Feature denominator changed')
    save_npz(FOLDER/'features.npz',ids=np.array(ids),values=np.array([vectors[k] for k in ids],dtype=np.float32).reshape(-1,4096),
             present=np.array([present[k] for k in ids],dtype=bool))
    checked(); private_json(output,{'complete':True,'main_plan_sha256':paired.sha(FOLDER/'plan.json'),
        'dataset_sha256':paired.sha(FOLDER/'dataset.json'),'features_sha256':paired.sha(FOLDER/'features.npz'),
        'available':len(ids),'unavailable':errors,'replay':replays,'cache_sources':caches,'gate':gate.identity,
        'reference_text_or_labels_in_model_input':False})
    print('SPECIFICITY FEATURES COMPLETE',len(ids),flush=True)


def summary(rows):
    if len({r['id'] for r in rows}) != len(rows): raise ValueError('Duplicate summary target')
    result = {}
    for group in ('all','front','back'):
        part = [r for r in rows if group == 'all' or r['expected_label'] == group]
        if any(r['decision'] not in ('change','match','unknown') for r in part): raise ValueError('Unknown decision')
        result[group] = {'targets':len(part),
            'false_nasal_changes':sum(r['decision']=='change' for r in part),
            'nasal_class_matches':sum(r['decision']=='match' for r in part),
            'unknown':sum(r['decision']=='unknown' for r in part),
            'whole_word_correctness_assessed':False}
    return result


def evaluate():
    from nasal_feature_probe import predict_ridge
    from nasal_feature_fusion import gate_scores
    from probe_phonetic_xeus import apply
    plan = checked(); dataset = dataset_checked(); pairs = checked_stage('pairs'); result = read_stage_result('pairs')
    output = FOLDER/'evaluation.json'
    if output.exists(): raise ValueError('Specificity evaluation already frozen')
    features = read(FOLDER/'feature-report.json')
    if (not features['complete'] or features['main_plan_sha256'] != paired.sha(FOLDER/'plan.json') or
        features['dataset_sha256'] != paired.sha(FOLDER/'dataset.json') or
        features['features_sha256'] != paired.sha(FOLDER/'features.npz')): raise ValueError('Feature provenance changed')
    for p,digest in features['cache_sources'].items():
        if paired.sha(p) != digest: raise ValueError('Feature cache changed')
    lookup = {r['id']:r for r in dataset['rows']}
    with np.load(plan['weights'],allow_pickle=False) as data: model = dict(data)
    with np.load(FOLDER/'features.npz',allow_pickle=False) as data:
        rows = [lookup[uid] for uid in data['ids'].tolist()]
        scores = predict_ridge(model,data['values']) if rows else np.empty((0,3))
        predicted = apply(rows,gate_scores(scores,data['present']),plan['policy'])
        present = dict(zip(data['ids'].tolist(),data['present'].tolist()))
    local = {r['id']:r for r in predicted}; observations = []; comparisons = {mode:[] for mode in MODES}
    for row in pairs['rows']:
        conditions = {c['name']:paired.observe(result['results'][c['key']]['result'],row,c['pinyin']) for c in row['conditions']}
        api = paired.compare_pair(conditions.get('expected',{}),conditions.get('opposite',{}))
        pred = local.get(row['id'],{})
        local_decision = 'change' if pred.get('candidate_nasal_change') else 'match' if pred.get('candidate_nasal_match') else 'unknown'
        observations.append({'id':row['id'],'api':api,'conditions':conditions,'local_decision':local_decision,
            'plain_state':row['api_state'],'speech_present':present.get(row['id']),
            'local_prediction':pred,'whole_pronunciation_correct':False})
        for mode in MODES:
            comparisons[mode].append({'id':row['id'],'expected_label':row['expected_label'],
                'decision':merged_decision(api['decision'],local_decision,mode)})
    reports = {mode:summary(rows) for mode,rows in comparisons.items()}
    private_json(output,{'complete':True,'main_plan_sha256':paired.sha(FOLDER/'plan.json'),
        'pairs_result_sha256':paired.sha(FOLDER/'pairs-result.json'),
        'feature_report_sha256':paired.sha(FOLDER/'feature-report.json'),'observations':observations,
        'comparisons':comparisons,'summary':reports,
        'plain_flagged':sum(r['plain_state']=='flagged' for r in observations),
        'preparation_failures':dict(Counter(r['preparation_failure'] for r in pairs['rows'] if 'preparation_failure' in r)),
        'no_new_training_or_calibration':True,'production_enabled':False,
        'whole_word_correctness_assessed':False,'same_explored_corpus':True})
    for mode,r in reports.items(): print('SPECIFICITY EVALUATED',mode,json.dumps(r['all']),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode',choices=['prepare','plain','pairs-prepare','pairs','extract','evaluate'])
    parser.add_argument('--allow-paid',action='store_true'); args = parser.parse_args()
    if args.mode in ('plain','pairs'): asyncio.run(run_stage(args.mode,args.allow_paid))
    else: {'prepare':prepare,'pairs-prepare':prepare_pairs,'extract':extract,'evaluate':evaluate}[args.mode]()
