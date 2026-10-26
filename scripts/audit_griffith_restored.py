"""Post-hoc timing diagnostic; never changes labels, models or denominators."""
import json
from pathlib import Path
import wave

from audit_nasal_pooling_boundaries import tail_coverage
from probe_griffith_restored import FOLDER, load_dataset, sha
from train_nasal_feature_probe import save_json


def main():
    dataset=load_dataset()
    evaluation=json.loads((FOLDER/'evaluation.json').read_text())
    features=json.loads((FOLDER/'feature-report.json').read_text())
    if not evaluation.get('complete') or evaluation['feature_report_sha256']!=sha(FOLDER/'feature-report.json'):
        raise ValueError('Incomplete or stale evaluation')
    if features['model']['receptive_field_samples']!=400 or features['model']['frame_stride_samples']!=320:
        raise ValueError('Timing helper does not match encoder geometry')
    output=FOLDER/'pooling-boundary-audit.json'
    if output.exists(): raise ValueError('Restored timing diagnostic frozen')
    rows=[]
    for row in dataset['rows']:
        with wave.open(row['audio'],'rb') as wav:
            count=wav.getnframes()
            if wav.getframerate()!=16000 or count>20*16000:
                raise ValueError('Diagnostic requires original full-utterance grid')
        rows.append({'id':row['id'],**tail_coverage(row['bounds'],row['human_syllable'],count)})
    if any(row['state']!='measured' for row in rows):
        raise ValueError('Unexpected empty frame pool')
    lookup={r['id']:r for r in rows}
    models={}
    for name,result in evaluation['comparison'].items():
        predictions=result['predictions']
        if len(predictions)!=len(rows) or {p['id'] for p in predictions}!=set(lookup):
            raise ValueError('Timing and prediction membership differ')
        groups={'all':predictions,
            'known_errors':[p for p in predictions if p['actual']!=p['expected']],
            'false_accusations':[p for p in predictions if p['candidate_nasal_change'] and p['actual']==p['expected']]}
        models[name]={group:{'targets':len(items),
            'majority_tail_centers_outside_human_syllable':sum(lookup[p['id']]['outside_fraction']>.5 for p in items)}
            for group,items in groups.items()}
    sources=[FOLDER/name for name in ('plan.json','implementation-amendment.json','dataset.json','feature-report.json','evaluation.json')]
    sources += [Path(__file__),Path('scripts/audit_nasal_pooling_boundaries.py')]
    report={'complete':True,'post_hoc':True,'sources':{str(p):sha(p) for p in sources},'comparison':models,'rows':rows,
        'limits':['Nominal frame centers do not bound the encoder receptive/contextual field.',
            'Published human times are syllable boundaries, not exact nasal-tail boundaries.',
            'Association does not prove timing caused a diagnostic error.',
            'No target removed, label changed or model/threshold selected.']}
    save_json(output,report)
    print(json.dumps(models,ensure_ascii=False))


if __name__=='__main__':
    main()
