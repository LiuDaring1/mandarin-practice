"""Import only prospectively selected LATIC WAVs from an official ZIP.

Never extracts arbitrary member paths, guesses IDs or replaces failed targets.
This checks container/annotation identity, not acoustic correctness or timing.
"""
import argparse
from collections import defaultdict, Counter
import hashlib
import io
import re
import stat
import subprocess
import wave
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from latic_validation_runtime import BASE,FOLDER,checked,selected_rows,sha
from train_nasal_feature_probe import save_json

TABLES={
    'expected_text':('SCRIPT/Suppose_text/total_transcript.txt',BASE/'latic-text-audit-v1/expected-text.txt'),
    'actual_text':('SCRIPT/Actual_text/total_transcript.txt',BASE/'latic-text-audit-v1/actual-text.txt'),
    'expected_pinyin':('SCRIPT/Suppose_Notations/total_notations_suppose.txt',BASE/'latic-source-audit-v1/suppose-notations.txt'),
    'actual_pinyin':('SCRIPT/Actual_Notations/total_notations_actual.txt',BASE/'latic-source-audit-v1/actual-notations.txt')}


def safe_member(info):
    path=PurePosixPath(info.filename)
    return (not path.is_absolute() and '..' not in path.parts and '\\' not in info.filename
            and not stat.S_ISLNK(info.external_attr>>16) and not info.is_dir())


def table_mapping(text):
    result={}
    for line in text.splitlines():
        if not line.strip():continue
        parts=line.split(maxsplit=1)
        if len(parts)!=2 or not re.fullmatch(r'\d{9}',parts[0]) or parts[0] in result:
            raise ValueError('Ambiguous/malformed official annotation identity')
        result[parts[0]]=parts[1]
    return result


def same_annotation(left,right,kind):
    # Pinyin token boundaries carry alignment information and must not vanish.
    return left.split()==right.split() if kind.endswith('pinyin') else ''.join(left.split())==''.join(right.split())


def index_archive(bundle):
    audio=defaultdict(list);tables={}
    for info in bundle.infolist():
        if not safe_member(info):continue
        parts=PurePosixPath(info.filename).parts
        if 'wava' in [p.casefold() for p in parts] and info.filename.lower().endswith('.wav'):
            stem=PurePosixPath(info.filename).stem
            if re.fullmatch(r'\d{9}',stem):audio[stem].append(info)
    for kind,(suffix,_) in TABLES.items():
        matches=[i for i in bundle.infolist() if safe_member(i) and
                 (i.filename.casefold()==suffix.casefold() or i.filename.casefold().endswith('/'+suffix.casefold()))]
        if len(matches)!=1:raise ValueError('Missing/ambiguous official table: '+kind)
        if matches[0].file_size>10_000_000:raise ValueError('Unexpected annotation table size')
        tables[kind]=(matches[0],table_mapping(bundle.read(matches[0]).decode('utf-8-sig')))
    return audio,tables


def audit_record(uid,audio,tables,expected):
    matches=audio.get(uid,[])
    if len(matches)!=1:return 'missing_audio' if not matches else 'ambiguous_audio_id'
    for kind,(_,mapping) in tables.items():
        if uid not in mapping or uid not in expected[kind]:return 'missing_'+kind
        if not same_annotation(mapping[uid],expected[kind][uid],kind):return 'conflicting_'+kind
    return None


def verify_wave(raw):
    with wave.open(io.BytesIO(raw),'rb') as source:
        channels=source.getnchannels();rate=source.getframerate();width=source.getsampwidth();frames=source.getnframes()
        if channels not in (1,2) or width not in (1,2,3,4) or not 8000<=rate<=96000 or not .1<=frames/rate<=180:
            raise ValueError('Unsupported WAV format or duration')
        data=source.readframes(frames)
        if len(data)!=frames*channels*width:raise ValueError('Truncated WAV payload')
    return {'channels':channels,'rate':rate,'sample_width':width,'frames':frames,'duration':frames/rate}


def run(archive):
    checked();output=FOLDER/'audio-import'
    if output.exists():raise ValueError('Audio import already exists; preserve it')
    rows=selected_rows();groups=defaultdict(list)
    for row in rows:groups[row['utterance_id']].append(row)
    expected={kind:table_mapping(path.read_text()) for kind,(_,path) in TABLES.items()}
    archive=archive.resolve();archive_sha=sha(archive);records=[];excluded=[]
    with ZipFile(archive) as bundle:
        audio,tables=index_archive(bundle)
        audits={uid:audit_record(uid,audio,tables,expected) for uid in groups}
        output.mkdir();(output/'audio').mkdir()
        save_json(output/'plan.json',{'archive':str(archive),'archive_sha256':archive_sha,
            'runner_plan_sha256':sha(FOLDER/'plan.json'),'selected_utterances':sorted(groups),
            'tables':{k:{'member':i.filename,'sha256':hashlib.sha256(bundle.read(i)).hexdigest()} for k,(i,_) in tables.items()},
            'selection_changed':False,'api_calls':0,'audits':audits})
        for uid,targets in groups.items():
            reason=audits[uid];info=audio.get(uid,[None])[0]
            if reason is None:
                try:
                    if info.file_size>100_000_000:raise ValueError('Unexpected WAV size')
                    raw=bundle.read(info);source_format=verify_wave(raw)
                    path=output/'audio'/(uid+'.wav')
                    subprocess.run(['ffmpeg','-v','error','-nostdin','-f','wav','-i','pipe:0',
                        '-ac','1','-ar','16000','-c:a','pcm_s16le',str(path)],input=raw,check=True,capture_output=True)
                    path.chmod(0o600);converted=verify_wave(path.read_bytes())
                    if (converted['channels'],converted['rate'],converted['sample_width'])!=(1,16000,2):
                        raise ValueError('Unexpected converted format')
                    if abs(converted['duration']-source_format['duration'])>.001:raise ValueError('Conversion changed duration')
                    records.append({'utterance_id':uid,'speaker':targets[0]['speaker'],'audio':str(path),
                        'audio_sha256':sha(path),'source_member':info.filename,
                        'source_audio_sha256':hashlib.sha256(raw).hexdigest(),
                        'source_format':source_format,'duration':converted['duration'],'reference':targets[0]['reference_text'],
                        'core':'read_sentence','targets':targets,'split':'external'})
                except (ValueError,wave.Error,EOFError,subprocess.CalledProcessError) as error:
                    reason=type(error).__name__+':'+str(error) if not isinstance(error,subprocess.CalledProcessError) else 'audio_conversion_failed'
            if reason is not None:excluded.append({'utterance_id':uid,'targets':targets,'reason':reason})
        if sum(len(r['targets']) for r in records+excluded)!=72:raise ValueError('Import lost targets')
        if sha(archive)!=archive_sha:raise ValueError('Archive changed while importing')
        save_json(output/'manifest.json',{'complete':True,'plan_sha256':sha(output/'plan.json'),
            'records':records,'excluded':excluded,'original_selected_targets':72,
            'imported_targets':sum(len(r['targets']) for r in records),'unavailable_targets':sum(len(r['targets']) for r in excluded),
            'failure_reasons':dict(Counter(r['reason'] for r in excluded)),'audio_identity_and_container_checked':True,
            'acoustic_boundaries_or_actual_pronunciation_validated':False,'model_outputs_seen':False,'api_calls':0})
    print('LATIC IMPORT',len(records),'recordings;',len(excluded),'unavailable; 72 targets retained',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('archive',type=Path);run(parser.parse_args().archive)
