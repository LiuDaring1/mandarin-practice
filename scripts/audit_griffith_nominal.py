"""Recover only equivalent ü/v/u: notation; never normalize nasal substitutions.

The old evaluation corpus remains immutable. This inventory introduces no model
prediction, acoustic score, API request or training membership.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from pypinyin import lazy_pinyin, Style
from prepare_griffith_nasal_probe import annotation_label, auxiliary_conflict, map_nominal, same_interval
from train_nasal_feature_probe import save_json

BASE = Path('data/derived/nasal-acoustic-validation')
FOLDER = BASE/'griffith-nominal-audit-v1'


def canonical_syllable(value):
    return re.sub(r'[0-4]$', '', value.strip()).replace('u:', 'v').replace('ü', 'v')


def map_nominal_canonical(items, reference):
    chars = ''.join(c for c in reference if '\u3400' <= c <= '\u9fff')
    expected = [canonical_syllable(v) for v in lazy_pinyin(chars, style=Style.NORMAL)]
    cursor = 0; result = []
    for index, row in enumerate(items):
        if row['text'].strip() in ('', 'pau', 'paus'):
            continue
        syllable = canonical_syllable(row['text'])
        if cursor >= len(chars):
            return None
        span = 1
        if syllable.endswith('r') and cursor+1 < len(chars) and chars[cursor+1]=='儿':
            syllable = syllable[:-1]; span = 2
        if syllable != expected[cursor]:
            return None
        result.append({'tier_index': index, 'position': cursor, 'char_span': span})
        cursor += span
    return result if cursor==len(chars) else None


def read_targets(rec, mapping):
    tiers = rec['tiers']; names = [k for k in ('ER', 'EI') if k in tiers]
    if len(names)!=1 or 'Misc' not in tiers:
        return [], [{'reason':'missing_or_ambiguous_error_tier'}]
    errors = tiers[names[0]]; misc = tiers['Misc']; nominal = tiers['NP']
    if len(errors)!=len(nominal) or len(misc)!=len(nominal):
        return [], [{'reason':'tier_length_mismatch'}]
    targets = []; excluded = []
    for item in mapping:
        i = item['tier_index']; n = nominal[i]
        if not same_interval(n, errors[i]) or not same_interval(n, misc[i]):
            excluded.append({'position':item['position'],'reason':'tier_time_mismatch'}); continue
        label = annotation_label(n['text'], errors[i]['text'], misc[i]['text'])
        if label['state'] in ('normal_annotation','nasal_substitution') and auxiliary_conflict(n, errors[i]['text'], tiers):
            label = {'state':'auxiliary_annotation_conflict'}
        if label['state'] in ('normal_annotation','nasal_substitution'):
            targets.append({**label,'position':item['position'],'human_syllable':[n['start'],n['end']],
                            'nominal_pinyin':n['text'],'annotation':errors[i]['text']})
        elif label['state']!='not_supported_nasal':
            excluded.append({'position':item['position'],'reason':label['state'],'annotation':errors[i]['text']})
    return targets, excluded


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    if FOLDER.exists():
        raise ValueError('Nominal spelling audit already frozen')
    paths = [BASE/'griffith'/name for name in ('source.json','annotations-v1.json','stimuli.json','segmental-tonal-errors-2014.pdf')]
    paths += [BASE/'griffith-external-v2/input.json',Path(__file__),Path('scripts/prepare_griffith_nasal_probe.py')]
    paths += [BASE/'kernel-classifier-v1'/name for name in ('plan.json','selection.json','evaluation.json')]
    plan = {'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'sources':{str(p):sha(p) for p in paths},
        'only_new_equivalence':'ü, v and u: notation in both nominal and reference syllables',
        'nasal_identity_unchanged':True,'full_sequence_required':True,'old_usable_mapping_must_replay':True,
        'label_parser':'unchanged explicit suffix/normal annotation and auxiliary-tier checks',
        'old_evaluation_unchanged':True,'new_records_usage':'evaluation only; no training or calibration',
        'new_samples_share_speakers_with_explored_corpus':True,'api_calls':0,'model_scores_used':False}
    FOLDER.mkdir();save_json(FOLDER/'plan.json',plan)
    source = json.loads((BASE/'griffith/annotations-v1.json').read_text())
    stimuli = json.loads((BASE/'griffith/stimuli.json').read_text())
    old = json.loads((BASE/'griffith-external-v2/input.json').read_text())
    old_members = {r['member'] for r in old['records']}
    replayed = []; restored = []; unresolved = []; newly_excluded = []
    for rec in source['rows']:
        numbers = re.findall(r'(?:^|_)(\d{2})(?:_|\.)',Path(rec['member']).name)
        if len(numbers)!=1 or numbers[0] not in stimuli or not rec['audio_exists']:
            unresolved.append({'member':rec['member'],'reason':'unmatched_stimulus_or_audio'}); continue
        reference = stimuli[numbers[0]]
        before = map_nominal(rec['tiers']['NP'],reference)
        after = map_nominal_canonical(rec['tiers']['NP'],reference)
        if before is not None:
            if before!=after:
                raise ValueError('Previously usable nominal mapping changed')
            replayed.append(rec['member']); continue
        if after is None:
            unresolved.append({'member':rec['member'],'reason':'full_nominal_sequence_mismatch'}); continue
        if rec['member'] in old_members:
            raise ValueError('Restored recording already in old selected evaluation')
        targets, excluded = read_targets(rec,after)
        newly_excluded.extend({'member':rec['member'],**item} for item in excluded)
        restored.append({**{k:rec[k] for k in ('member','speaker','audio_member','annotation_sha256')},
            'reference':reference,'targets':targets,'full_nominal_mapping':after,'split':'external',
            'restoration_reason':'equivalent_umlaut_spelling_only'})
    for path,digest in plan['sources'].items():
        if sha(path)!=digest:
            raise ValueError('Nominal audit source changed')
    report = {'complete':True,'plan_sha256':sha(FOLDER/'plan.json'),'source_recordings':len(source['rows']),
        'replayed_mapping_count':len(replayed),'restored_recordings':len(restored),'records':restored,
        'still_unresolved':unresolved,'newly_excluded_targets':newly_excluded,
        'restored_target_counts':dict(Counter(t['state'] for r in restored for t in r['targets'])),
        'restored_speakers':len({r['speaker'] for r in restored}),
        'new_targets_used_for_training':False,'model_scores_observed':False,'api_calls':0}
    save_json(FOLDER/'inventory.json',report)
    print('NOMINAL AUDIT',len(replayed),'unchanged;',len(restored),'restored recordings;',len(unresolved),'unresolved;',
          json.dumps(report['restored_target_counts']),len(newly_excluded),'excluded targets',flush=True)


if __name__=='__main__':
    main()
