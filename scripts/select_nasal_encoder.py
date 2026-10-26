"""Choose between frozen feature candidates using development evidence only."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path


def choose(candidates):
    if len({c['selection']['dataset_sha256'] for c in candidates})!=1:
        raise ValueError('Encoder candidates used different datasets')
    for key in ['train_ids','dev_ids']:
        if any(c['selection'][key]!=candidates[0]['selection'][key] for c in candidates):
            raise ValueError('Encoder candidates used different partitions')
    ranked=[]
    for candidate in candidates:
        selection=candidate['selection'];margin=selection['review_margin']
        entry=next((r for r in selection['development_margin_table'] if r['margin']==margin),None)
        safe_directions=entry['correct_error_directions'] if entry and entry['false_nasal_accusations']==0 else 0
        ranked.append({'directory':candidate['directory'],'development_safe_directions':safe_directions,
                       'development_balanced_accuracy':selection['selected']['dev_balanced_accuracy'],
                       'review_margin':margin,'selected':selection['selected']})
    ranked.sort(key=lambda r:(-r['development_safe_directions'],-r['development_balanced_accuracy'],r['directory']))
    return ranked


def main(args):
    output=Path(args.output)
    if output.exists():
        raise ValueError('Encoder selection already frozen')
    candidates=[{'directory':directory,'selection':json.loads((Path(directory)/'selection.json').read_text())}
                for directory in args.directories]
    ranked=choose(candidates)
    report={'selected_at_utc':datetime.now(timezone.utc).isoformat(),'winner':ranked[0]['directory'],
            'selection_rule':'development detected-error count with zero false nasal accusations; then balanced label accuracy',
            'test_or_transfer_predictions_used':False,'candidates':ranked}
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');output.chmod(0o600)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--directories',nargs='+',required=True)
    parser.add_argument('--output',required=True)
    main(parser.parse_args())
