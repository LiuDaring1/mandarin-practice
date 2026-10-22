"""Build private news candidates using independent ASR and forced timestamps.

No app release is changed here. Arabic-number sentences are held for a later
spoken-number review, rather than deleting their numbers during alignment.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import wave

from pth_corpus.sentence_reading import hanzi_pinyin, is_hanzi, score_sentence, select_reason


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT/'data/raw/news-wechat-v1'
OUT = ROOT/'data/derived/news-sentence-v1'


def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def extract_article(raw):
    if not re.fullmatch(r'\d{8,12}-\d{1,2}',raw['article_id']):raise ValueError('invalid article identifier')
    if raw['text'].count('原文试读') != 1 or '新闻摘自' not in raw['text']:
        raise ValueError('unrecognized article format')
    section=raw['text'].split('原文试读',1)[1].split('新闻摘自',1)[0].strip()
    paragraphs=[p.strip() for p in re.split(r'\n\s*\n',section) if p.strip()]
    if len(paragraphs)<2:raise ValueError('no news body')
    title=paragraphs[0]
    body=re.sub(r'\s+','',''.join(paragraphs[1:]))
    sentences=[]
    for seq,match in enumerate(re.finditer(r'[^。！？；]+[。！？；]',body),1):
        text=match.group().strip().lstrip('”’」』')
        closing=re.match(r'[”’」』]+',body[match.end():])
        if closing:text+=closing.group()
        sentences.append({'sentence_id':f"news-{raw['article_id']}-{seq:04d}",'text':text,
                          'text_offset':match.start()})
    return title,body,sentences


def process(raw_file,aligner,whisper):
    raw=json.loads(raw_file.read_text())
    if len(raw['audio_files'])!=1:raise ValueError('multiple audio tracks require explicit mapping')
    audio=RAW/raw['audio_files'][0]['file']
    title,body,sentences=extract_article(raw)
    eligible=[s for s in sentences if not re.search(r'[0-9A-Za-z]',s['text']) and 15<=score_sentence(s['text'])['char_count']<=65 and select_reason(score_sentence(s['text']))]
    if not eligible:return {'algorithm_version':4,'article_id':raw['article_id'],'title':title,'sentences':[],'holds':[],'reason':'no eligible complete sentences'}
    result=aligner.generate(audio=str(audio),text=body,language='Chinese')
    tokens=[]
    for item in result.items:
        chars=[ch for ch in item.text if is_hanzi(ch)]
        for i,ch in enumerate(chars):
            length=(item.end_time-item.start_time)/max(1,len(chars))
            tokens.append({'text':ch,'start':item.start_time+i*length,'end':item.start_time+(i+1)*length})
    if ''.join(t['text'] for t in tokens) != ''.join(ch for ch in body if is_hanzi(ch)):
        raise ValueError('forced alignment changed reference characters')
    asr_result=whisper.generate(str(audio),language='zh',word_timestamps=True,temperature=0,
                                   condition_on_previous_text=False,verbose=None)
    asr=asr_result.segments
    audio_duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(audio)]))
    asr_tokens=[]
    for segment in asr:
        for word in segment.get('words',[]):
            chars=[ch for ch in word['word'] if is_hanzi(ch)]
            for i,ch in enumerate(chars):
                duration=(word['end']-word['start'])/max(1,len(chars))
                asr_tokens.append({'text':ch,'start':word['start']+i*duration,'end':word['start']+(i+1)*duration})
    def phonetics(text):return [re.sub(r'[0-9]','',py) for py in hanzi_pinyin(text)]
    rows=[];holds=[]
    for seq,sentence in enumerate(sentences,1):
        text=sentence['text'];metrics=score_sentence(text)
        if not 15<=metrics['char_count']<=65 or re.search(r'[0-9A-Za-z]',text) or not select_reason(metrics):continue
        if text.startswith(('他表示','她表示','对此','上述','这也是')):continue
        sid=sentence['sentence_id']
        offset=sum(is_hanzi(ch) for ch in body[:sentence['text_offset']])
        end_index=offset+metrics['char_count']-1
        first,last=tokens[offset],tokens[end_index]
        observed=''.join(t['text'] for t in asr_tokens if t['end']>first['start']+.02 and t['start']<last['end']-.02)
        reference=''.join(ch for ch in text if is_hanzi(ch))
        ref_py,obs_py=phonetics(reference),phonetics(observed)
        char_score=difflib.SequenceMatcher(None,reference,observed,autojunk=False).ratio()
        py_score=difflib.SequenceMatcher(None,ref_py,obs_py,autojunk=False).ratio()
        score=.15*char_score+.85*py_score
        edges=bool(obs_py) and ref_py[0] in obs_py[:2] and ref_py[-1] in obs_py[-2:]
        if score<.88 or not edges:
            holds.append({'sentence_id':sid,'reason':'independent ASR and timestamps disagree','score':score,'observed':observed});continue
        start=max(0,first['start']-.16)
        end=min(audio_duration,last['end']+.2)
        if offset and tokens[offset-1]['end']<first['start']:
            start=max(start,(tokens[offset-1]['end']+first['start'])/2)
        if end_index+1<len(tokens) and last['end']<tokens[end_index+1]['start']:
            end=min(end,(last['end']+tokens[end_index+1]['start'])/2)
        if not 3<=end-start<=23:continue
        relative=f'clips/{sid}.wav';target=OUT/relative;target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            subprocess.run(['ffmpeg','-v','error','-nostdin','-n','-ss',str(start),'-i',str(audio),
                '-t',str(end-start),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(target)],check=True)
        with wave.open(str(target),'rb') as f:duration=f.getnframes()/f.getframerate()
        rows.append({**metrics,'sentence_id':sid,'article_id':'news-'+raw['article_id'],
            'article_title':title,'page':0,'seq':seq,'text':text,'spoken_text':text,
            'genre':'news','source_url':raw['url'],'published':raw.get('published'),
            'select_reason':'news-density','clip_rel':relative,'clip_duration':duration,
            'clip_sha256':digest(target),'confidence':round(score,4),'tier':'high',
            'original_relative_path':'derived/news-sentence-v1/'+relative,
            'source_audio':str(audio),'source_sha256':digest(audio),
            'src_start':round(start,4),'src_end':round(end,4),
            'first_char_start':first['start'],'last_char_end':last['end']})
    return {'algorithm_version':4,'article_id':raw['article_id'],'source_url':raw['url'],'title':title,
            'asr':asr,'forced_alignment':result.segments,'sentences':rows,'holds':holds}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--watch',action='store_true');args=parser.parse_args()
    from transformers import WhisperProcessor, GenerationConfig
    from mlx_audio.stt.utils import load_model
    aligner=load_model('mlx-community/Qwen3-ForcedAligner-0.6B-8bit')
    whisper=load_model('mlx-community/whisper-small-mlx')
    whisper._processor=WhisperProcessor.from_pretrained('openai/whisper-small')
    whisper.set_alignment_heads(GenerationConfig.from_pretrained('openai/whisper-small').alignment_heads)
    records=OUT/'articles';records.mkdir(parents=True,exist_ok=True)
    attempted=set();processed=0;count=0
    for iteration in range(720):
        pending=[]
        for path in sorted(RAW.glob('*.json'),reverse=True):
            if path.stem in attempted:continue
            if (records/path.name).exists() and json.loads((records/path.name).read_text()).get('algorithm_version')==4:continue
            try:raw=json.loads(path.read_text())
            except ValueError:continue
            if not isinstance(raw,dict) or not raw.get('audio_files'):continue
            if not all((RAW/a['file']).is_file() for a in raw['audio_files']):continue
            pending.append(path)
        for path in pending:
            attempted.add(path.stem)
            try:
                result=process(path,aligner,whisper)
                (records/path.name).write_text(json.dumps(result,ensure_ascii=False))
                processed+=1;count+=len(result['sentences'])
                if processed%10==0:print(json.dumps({'processed_articles':processed,'new_candidates':count}),flush=True)
            except Exception as exc:
                with (OUT/'errors.jsonl').open('a') as f:f.write(json.dumps({'article':path.stem,'error':str(exc)[:250]})+'\n')
        if not args.watch or ((RAW/'collection-complete.json').exists() and not pending):break
        time.sleep(5)
    rows=[row for path in records.glob('*.json') for row in json.loads(path.read_text())['sentences']]
    (OUT/'candidates.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    print(json.dumps({'complete':True,'candidates':len(rows),'articles':len(list(records.glob('*.json')))}),flush=True)


if __name__=='__main__':main()
