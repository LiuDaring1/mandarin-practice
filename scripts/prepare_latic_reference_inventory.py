"""Freeze reference mapping and same-speaker controls before audio inference."""
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

from audit_latic_nasal_annotations import read_notations
from latic_reference_mapping import map_reference
from probe_eduhk_nasal import model_final
from probe_nasal_pairs import sha
from train_nasal_feature_probe import save_json

BASE = Path('data/derived/nasal-acoustic-validation')
FOLDER = BASE/'latic-text-audit-v1'


def main():
    output = FOLDER/'inventory.json'
    if output.exists():raise ValueError('LATIC reference inventory frozen')
    source = json.loads((FOLDER/'source.json').read_text())
    for row in source['sources']:
        if sha(FOLDER/row['file'])!=row['sha256']:raise ValueError('Text source changed')
    reference = read_notations(BASE/'latic-source-audit-v1/suppose-notations.txt')
    # Reuse identity validation, but preserve whitespace inside each reference.
    identities = read_notations(FOLDER/'expected-text.txt')
    texts = dict(line.split(maxsplit=1) for line in (FOLDER/'expected-text.txt').read_text().splitlines() if line.strip())
    if set(identities)!=set(texts):raise ValueError('Reference text identity changed')
    old = json.loads((BASE/'latic-alignment-audit-v2/inventory.json').read_text())
    for path,digest in old['sources'].items():
        if sha(path)!=digest:raise ValueError('Annotation inventory source changed')
    if set(reference)!=set(texts) or set(reference)!={r['id'] for r in old['records']}:
        raise ValueError('Reference/annotation identity membership changed')
    mapped = {}; failures = []
    for uid in sorted(reference):
        try:mapped[uid]=map_reference(texts[uid],reference[uid])
        except ValueError as error:failures.append({'id':uid,'reason':str(error)})
    targets = []; reasons = {r['id']:r['reason'] for r in failures}
    for row in old['records']:
        for t in row['targets']:
            key = t['token_position']; mapping = mapped[row['id']][key] if row['id'] in mapped else None
            if mapping and mapping['expected_pinyin']!=t['expected_pinyin']:
                raise ValueError('Nasal target reference changed')
            targets.append({**t,'utterance_id':row['id'],'id':row['id']+':'+str(key),'speaker':row['speaker'],
                'expected_final':model_final(t['expected_pinyin']),'reference_mapping':mapping,'reference_text':texts[row['id']],
                'reference_unavailable_reason':reasons.get(row['id']),'audio_obtained':False})
    errors = [t for t in targets if t['expected_label']!=t['actual_label']]
    normals = [t for t in targets if t['expected_label']==t['actual_label'] and t['reference_mapping']]
    used = set(); controls = []; missing = []
    for error in sorted(errors,key=lambda r:r['id']):
        candidates = [t for t in normals if t['id'] not in used and t['speaker']==error['speaker'] and t['expected_final']==error['expected_final']]
        def order(t):
            digest = hashlib.sha256(('latic-controls-v1|'+error['id']+'|'+t['id']).encode()).hexdigest()
            return (t['expected_pinyin']!=error['expected_pinyin'],t['utterance_id']==error['utterance_id'],digest)
        candidates.sort(key=order)
        for t in candidates[:3]:
            used.add(t['id']);controls.append({**t,'matched_error':error['id']})
        if len(candidates)<3:missing.append({'error_id':error['id'],'missing_controls':3-len(candidates)})
    paths = [FOLDER/n for n in ('source.json','expected-text.txt','actual-text.txt')]
    paths += [BASE/'latic-alignment-audit-v2/inventory.json',Path(__file__),Path('scripts/latic_reference_mapping.py')]
    counts = {'reference_utterances':len(reference),'mapped_utterances':len(mapped),'unavailable_utterances':len(failures),
        'failure_reasons':dict(Counter(r['reason'] for r in failures)),
        'selected_errors':len(errors),'mapped_errors':sum(t['reference_mapping'] is not None for t in errors),
        'selected_controls':len(controls),'missing_controls':sum(r['missing_controls'] for r in missing),
        'selected_utterances':len({r['utterance_id'] for r in errors+controls}),'selected_speakers':len({r['speaker'] for r in errors+controls}),
        'error_directions':dict(Counter(t['expected_label']+'->'+t['actual_label'] for t in errors))}
    save_json(output,{'complete':True,'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'sources':{str(p):sha(p) for p in paths},'counts':counts,'reference_failures':failures,
        'errors':errors,'controls':controls,'missing_controls':missing,
        'control_selection':'3 unique normal-notation targets per error, same speaker and exact expected final; prefer same expected syllable, then another utterance, then SHA256 order',
        'selection_used_audio_or_predictions':False,'split':'external_validation_only','training_allowed':False,
        'audio_obtained':False,'audio_identity_or_timing_validated':False,'scoring_complete':False,
        'limits':['Hanzi/pinyin reference agreement is not an acoustic boundary or actual-pronunciation check.',
                  'All 18 annotation errors remain selected, including unavailable reference mappings.',
                  'Normal notation is a corpus annotation, not a verified personal recording.',
                  'Original actual-token mappings and all ambiguous/other-segment errors stay in the parent inventory.']})
    print('LATIC REFERENCE AND CONTROL INVENTORY',json.dumps(counts),flush=True)


if __name__=='__main__':main()
