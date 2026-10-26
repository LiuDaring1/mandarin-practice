"""Cache-only, post-hoc audit of contradictory positive feedback.

This is a diagnostic experiment after inspecting a holdout counterexample, not
an independent validation. It cannot alter the frozen classifier or app policy.
"""
import asyncio
import json
from pathlib import Path

from ise_probe import IseProbe, public_result, target_at
from train_nasal_feature_probe import save_json, summarize


def veto_conflict(observation, api_state):
    return {**observation, 'candidate_nasal_match': bool(observation['candidate_nasal_match']
                                                       and api_state == 'not_flagged'),
            'api_state':api_state}


async def main():
    base=Path('data/derived/nasal-acoustic-validation')
    output_path=base/'feature-feedback-v3/api-veto-audit.json'
    if output_path.exists():
        raise ValueError('Post-hoc audit is already frozen')
    ledger=Path('data/derived/ise-validation/requests.json');before=ledger.read_bytes()
    original={r['id']:r['core'] for r in json.loads((base/'ise-word-calibration-input.json').read_text())['cases']}
    probe=IseProbe(ledger.parent,allow_paid=False)
    output={'post_hoc':True,
            'purpose':'Audit API contradictions after observing the new holdout false reassurance; not an independent validation of a new rule.',
            'new_calls':0,'reports':{}}
    for name,data_folder,evaluation_folder in [
            ('original',base/'feature-classifier-v2-phoneme',base/'feature-feedback-v3'),
            ('fresh',base/'feedback-v3-holdout',base/'feedback-v3-holdout')]:
        rows={r['id']:r for r in json.loads((data_folder/'dataset.json').read_text())['rows']}
        predictions=json.loads((evaluation_folder/'evaluation.json').read_text())['predictions']
        adjusted=[]
        for observation in predictions:
            row=rows[observation['id']];updated=dict(observation)
            if observation['candidate_nasal_match']:
                core=original[row['id']] if row['condition']=='word_error' else 'read_sentence'
                response=public_result(await probe.call(row['audio'],row['reference'],core=core))
                state=target_at(response,row['reference'],row['position'])['state']
                updated=veto_conflict(observation,state)
            adjusted.append(updated)
        output['reports'][name]={split:summarize([r for r in adjusted if r['split']==split])
                                 for split in sorted({r['split'] for r in adjusted})}
    if before!=ledger.read_bytes():
        raise ValueError('Cache-only audit changed the request ledger')
    save_json(output_path,output)
    print('Post-hoc audit saved; no production policy changed')


if __name__=='__main__':
    asyncio.run(main())
