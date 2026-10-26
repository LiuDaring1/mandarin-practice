"""Aggregate frozen classifier evidence without exporting source recordings."""
from collections import Counter
import json
from pathlib import Path


def stage(folder):
    evaluation=json.loads((folder/'evaluation.json').read_text())
    selection=json.loads((folder/'selection.json').read_text())
    dataset=json.loads((folder/'dataset.json').read_text())
    if evaluation.get('complete') is not True:
        raise ValueError('Incomplete classifier evaluation')
    return {'selected':selection['selected'],'review_margin':selection['review_margin'],
            'matching_margin':selection.get('matching_margin'),
            'dataset_sha256':selection['dataset_sha256'],'weights_sha256':selection['weights_sha256'],
            'encoder_frozen':selection['encoder_frozen'],'test_rows_used_for_selection':selection['evaluation_rows_used_for_selection'],
            'data':{split:{'rows':sum(r['split']==split for r in dataset['rows']),
                          'speakers':len({r['speaker'] for r in dataset['rows'] if r['split']==split}),
                          'actual_labels':dict(Counter(r['actual_label'] for r in dataset['rows'] if r['split']==split))}
                    for split in ['train','dev','test','transfer']},
            'results':evaluation['splits']}


def main():
    base=Path('data/derived/nasal-acoustic-validation')
    choice=json.loads((base/'feature-classifier-v2-choice.json').read_text())
    expansion=json.loads((base/'ompal/expansion-ise.json').read_text())
    if expansion.get('complete') is not True:
        raise ValueError('Expansion request batch incomplete')
    report={'scope':'Frozen acoustic features with speaker-separated ridge classification; research only',
            'initial':stage(base/'feature-classifier-v1'),
            'expanded':stage(Path(choice['winner'])),
            'encoder_choice':{**choice,'winner':Path(choice['winner']).name,
                'candidates':[{**r,'directory':Path(r['directory']).name} for r in choice['candidates']]},
            'api_expansion':{**{k:expansion[k] for k in ['ledger_before','ledger_after','new_calls']},
                             'statuses':dict(Counter(r['ise_status'] for r in expansion['cases']))},
            'limits':['Automatic word crops and API time intervals are not independently human-audited.',
                      'Previously explored public recordings do not constitute untouched product validation.',
                      'The nine continuous-reading error targets have no matched same-speaker normal controls.',
                      'Classifier scores/gaps are not correctness probabilities.',
                      'No live microphone/mobile/production feedback has been enabled.'],
            'sources':['https://lml-elearning.eduhk.hk/about_g.aspx',
                       'https://github.com/phantomhsieh/OMPAL-corpus/tree/c3aaa9e892e4b1c2a25b637401f52f6e35b53e74']}
    feedback=base/'feature-feedback-v3'
    selection=json.loads((feedback/'selection.json').read_text())
    evaluation=json.loads((feedback/'evaluation.json').read_text())
    holdout=base/'feedback-v3-holdout'
    holdout_eval=json.loads((holdout/'evaluation.json').read_text())
    holdout_api=json.loads((holdout/'ise.json').read_text())
    holdout_manifest=json.loads((holdout/'input.json').read_text())
    holdout_dataset=json.loads((holdout/'dataset.json').read_text())
    if not all(r.get('complete') is True for r in [evaluation,holdout_eval,holdout_api]):
        raise ValueError('Feedback experiment is incomplete')
    report['feedback_selection']={
        'selected':evaluation['selected'],'weights_sha256':selection['weights_sha256'],
        'selection_used_test_or_transfer':selection['test_or_transfer_used_for_selection'],
        'rule':'Development zero observed false accusations, >=3 detected errors and both directions; matching margin calibrated separately.',
        'results':evaluation['splits'],
        'fresh_recordings':{'recordings':len(holdout_manifest['recordings']),
            'speakers':len({r['speaker'] for r in holdout_manifest['recordings']}),
            'targets_before_alignment':sum(len(r['targets']) for r in holdout_manifest['recordings']),
            'excluded_duration_targets':sum(r['target_count'] for r in holdout_manifest['excluded']),
            'excluded_total_targets':sum(r['target_count'] for r in holdout_dataset['excluded']),
            'dataset_sha256':holdout_eval['dataset_sha256'],
            'api':{**{k:holdout_api[k] for k in ['ledger_before','ledger_after','new_calls']},
                   'statuses':dict(Counter(r['ise_status'] for r in holdout_api['cases']))},
            'results':holdout_eval['splits']},
        'limits':['The same development data was reused for exploratory model selection.',
                  'New recordings are disjoint from fitting/development speakers but use previously explored public corpora.',
                  'Normal and error labels come from different corpora; no matched within-speaker correctness study.',
                  'No observed false accusation in a small sample is not a statistical guarantee.']}
    audit=json.loads((feedback/'api-veto-audit.json').read_text())
    if audit.get('post_hoc') is not True or audit.get('new_calls') != 0:
        raise ValueError('Expected a clearly marked cache-only post-hoc audit')
    report['post_hoc_api_contradiction_audit']=audit
    output=Path('handoff/nasal-feature-probe-2026-10-27/report.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('report written',output)


if __name__=='__main__':
    main()
