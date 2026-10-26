"""Publish aggregate evidence only; never audio, credentials or raw API XML."""
from collections import Counter
import json
from pathlib import Path


def completed_rows(path):
    report = json.loads(Path(path).read_text())
    if report.get('complete') is not True:
        raise ValueError('Refusing to summarize an unfinished experiment')
    rows = report['cases']
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate target identity')
    return rows


def consensus(row, minimum_gap=0):
    window = row['windows']['syllable_0.0']
    return (row['ise_observation']['state'] == 'flagged'
            and window.get('state') == 'observed'
            and window['best_token'] == window['opposite']
            and window['decoded_tokens'] == [window['opposite']]
            and window['best_minus_runner_up'] >= minimum_gap)


def summarize(rows):
    result = {}
    for condition in sorted({r['condition'] for r in rows}):
        group = [r for r in rows if r['condition'] == condition]
        api = [r for r in group if r['ise_observation']['state'] == 'flagged']
        local = [r for r in group if r['local']['best_hypothesis'] == 'opposite']
        combined = [r for r in local if r['ise_observation']['state'] == 'flagged']
        result[condition] = {'targets':len(group),
            'ise_states':dict(Counter(r['ise_observation']['state'] for r in group)),
            'api_vowel_flag':len(api), 'global_opposite_best':len(local),
            'global_opposite_and_api':len(combined),
            'syllable_consensus_sensitivity':{str(gap):{
                'flagged':sum(consensus(r, gap) for r in group),
                'directions':dict(Counter('ng_to_n' if r['local']['final'].endswith('ng') else 'n_to_ng'
                                        for r in group if consensus(r, gap)))} for gap in (0,1,2,3)}}
    return result


def main():
    base = Path('data/derived/nasal-acoustic-validation')
    paths = [base/'word-windows.json', base/'ompal/windows.json', base/'eduhk-passages/windows.json']
    rows = [r for path in paths for r in completed_rows(path)]
    ledger = json.loads(Path('data/derived/ise-validation/requests.json').read_text())
    passage_input = json.loads((base/'eduhk-passages/probe-input.json').read_text())
    annotations = json.loads((base/'eduhk-passages/annotations.json').read_text())
    report = {
        'scope':'Research observations on public recordings; no production diagnostic accuracy claim',
        'conditions':summarize(rows),
        'ise_ledger_total':len(ledger),
        'ise_ledger_before_this_milestone':78,
        'new_requests_including_transport_failure':len(ledger)-78,
        'word_error_inventory':{'annotated':92, 'scored':51, 'not_located':41},
        'sentence_error_inventory':{
            'public_passages':len(annotations['rows']),
            'annotated_targets':sum(len(r['nasal_errors']) for r in annotations['rows']),
            'selected_speakers':passage_input['selected_speakers'],
            'evaluated_recordings':len(passage_input['recordings']),
            'evaluated_targets':len(passage_input['cases']),
            'excluded':passage_input['excluded']},
        'limits':[
            'Word crops use automatic alignment and have not received human boundary audit.',
            'Unmarked EdUHK characters are not certified correct controls.',
            'Beijing reference-file designation is not per-phone expert confirmation.',
            'OMPAL learner positives require at least three unanimous vowel scores and matching aggregate identity.',
            'OMPAL native scores are reported separately from teacher-vote positives.',
            'One failed API request remains cached/unknown; it was not retried or removed.',
            'CTC likelihood and score gaps are not calibrated correctness probabilities.',
            'The threshold table is exploratory; none is approved for deployment.',
            'Continuous-reading speakers are outside the word-error batch, not a fully untouched speaker holdout.',
            'No automatic correctness/pass verdict or production feedback has been enabled.'
        ],
        'sources':[
            'https://www.xfyun.cn/doc/Ise/IseAPI.html',
            'https://www.xfyun.cn/doc/voiceservice/ise/ise_faq.html',
            'https://lml-elearning.eduhk.hk/about_g.aspx',
            'https://github.com/phantomhsieh/OMPAL-corpus/tree/c3aaa9e892e4b1c2a25b637401f52f6e35b53e74'
        ]
    }
    output = Path('handoff/nasal-calibration-2026-10-27/report.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report['conditions'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
