"""Model-blind two-recording expansion per available learner speaker.

Keep the original fixed source revision and exact ID joins. This does not inspect
classifier outputs or select known failures. Only unanimous vowel labels enter.
"""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

from pypinyin import lazy_pinyin,Style

from prepare_ompal_controls import unanimous_correct
from probe_eduhk_nasal import model_final


SELECTION_SEED='ompal-normal-expansion-20261027-v1'


def main():
    from opencc import OpenCC
    converter=OpenCC('tw2s')
    folder=Path('data/derived/nasal-acoustic-validation/ompal')
    output=folder/'expansion-input.json'
    if output.exists():
        raise ValueError('Expansion already frozen; do not silently resample')
    raw=json.loads((folder/'non-native_scores-detail.json').read_text())
    summary=json.loads((folder/'non-native_scores.json').read_text())
    revision=json.loads((folder/'source-revision.json').read_text())['commit']
    tree=json.loads((folder/'tree.json').read_text())['tree']
    paths={Path(r['path']).stem:r['path'] for r in tree if r['path'].endswith('.wav')}
    used={r['uid'] for r in json.loads((folder/'controls-input.json').read_text())['recordings']}
    pools=defaultdict(list)
    for uid,record in raw.items():
        if uid in used or uid not in paths or uid not in summary:
            continue
        other=summary[uid]
        if record['text']!=other['text'] or [w['text'] for w in record['words']] != [w['text'] for w in other['words']]:
            raise ValueError('Annotation identity mismatch')
        if any(len(w['text'])!=1 or len(w['text'][0])!=1 for w in record['words']):
            continue
        chars=''.join(c for c in record['text'] if '\u3400'<=c<='\u9fff')
        if ''.join(w['text'][0] for w in record['words'])!=chars:
            continue
        reference=converter.convert(chars)
        if len(reference)!=len(chars):
            continue
        finals=[model_final(p) for p in lazy_pinyin(reference,style=Style.NORMAL)]
        targets=[]
        for pos,word in enumerate(record['words']):
            if unanimous_correct(word['phoneme_vowel']):
                if other['words'][pos]['phoneme_vowel']!=1:
                    raise ValueError('Conflicting labels')
                targets.append({'position':pos,'final':finals[pos],'published_vowel_scores':word['phoneme_vowel']})
        if sum(t['final'].endswith(('n','ng')) for t in targets)>=2:
            pools[uid[:6]].append({'uid':uid,'speaker':uid[:6],'reference':reference,'finals':finals,
                                  'targets':targets,'condition':'unanimous_learner_vowel_correct'})
    selected=[]
    for speaker in sorted(pools):
        candidates=sorted(pools[speaker],key=lambda r:hashlib.sha256((SELECTION_SEED+r['uid']).encode()).hexdigest())
        selected.extend(candidates[:2])
    cases=[]
    for record in selected:
        uid=record['uid'];source=folder/'audio'/(uid+'-source.wav');audio=folder/'audio'/(uid+'.wav')
        url=f'https://raw.githubusercontent.com/phantomhsieh/OMPAL-corpus/{revision}/{paths[uid]}'
        if not source.exists():
            source.write_bytes(urllib.request.urlopen(url,timeout=30).read())
        if not audio.exists():
            subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(source),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(audio)],check=True)
        record.update(audio=str(audio),source_url=url,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                      audio_sha256=hashlib.sha256(audio.read_bytes()).hexdigest())
        # One carrier target per recording triggers only one cached API request.
        target=record['targets'][0]
        cases.append({'id':f'expansion-{uid}','audio':str(audio),'reference':record['reference'],
                      'position':target['position'],'core':'read_sentence','condition':'teacher_correct_carrier'})
        print(uid,'teacher_correct_targets',len(record['targets']),flush=True)
    output.write_text(json.dumps({'source_revision':revision,'selection_seed':SELECTION_SEED,
        'selection_used_model_outputs':False,'recordings':selected,'cases':cases},ensure_ascii=False,indent=2))
    output.chmod(0o600)
    print('COMPLETE',len(selected),'recordings',len(pools),'speakers',flush=True)


if __name__=='__main__':
    main()
