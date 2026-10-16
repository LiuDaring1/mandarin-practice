"""Public-file preparation for supervised Jianying multi-clip conversion."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import subprocess
import contextlib
import io
import voice_conversion_batch as vc


def clone_voice(batch, source_batch, voice):
    if batch.exists():
        raise ValueError('Refuse to overwrite an existing voice batch')
    if voice not in ('news-female', 'news-male'):
        raise ValueError('Unsupported target voice')
    original = json.loads((source_batch / 'queue.json').read_text())['jobs']
    jobs = []
    for job in original:
        if job['kind'] == 'repair':
            continue
        if vc.digest(Path(job['source'])) != job['source_sha256']:
            raise ValueError('Original changed before second voice: ' + job['id'])
        copy = {**job, 'voice': voice,
                'export_name': job['export_name'].rsplit('__', 1)[0] + '__' + voice + '.wav'}
        jobs.append(copy)
    if not jobs:
        raise ValueError('No original jobs to convert')
    vc.write_json(batch / 'queue.json', {'version': 1, 'jobs': jobs})
    for name in ('inputs', 'exports', 'reports'):
        (batch / name).mkdir(exist_ok=True)
    print('Prepared independent voice batch:', voice, len(jobs), 'jobs;',
          sum(len(j['clips']) for j in jobs), 'clips')


def prepare(batch, size=30):
    root = batch / 'groups'
    plan = root / 'plan.json'
    if plan.exists():
        return json.loads(plan.read_text())
    jobs = json.loads((batch / 'queue.json').read_text())['jobs']
    reservations = batch / 'manual-assignments.json'
    assigned = set(json.loads(reservations.read_text())['jobs']) if reservations.exists() else set()
    pending = [j for j in jobs if j['kind'] != 'repair' and j['id'] not in assigned
               and not (batch / 'exports' / j['export_name']).exists()]
    groups = []
    for i in range(0, len(pending), size):
        voice = pending[i].get('voice', 'news-female')
        if any(j.get('voice', 'news-female') != voice for j in pending[i:i + size]):
            raise ValueError('A group must use one voice')
        gid = f'group-{i // size + 2:03}'
        rows, cursor = [], 0
        for j in pending[i:i + size]:
            duration = math.ceil(j['duration'] * 10) / 10
            if duration >= 570:
                raise ValueError('Input requires subdivision before GUI processing')
            samples = round(duration * 16000)
            rows.append({'job': j['id'], 'source': j['source'],
                'source_sha256': j['source_sha256'], 'duration': duration,
                'start_sample': cursor, 'samples': samples,
                'file': f"{voice}__{len(rows)+1:03}__{j['id'].split('-',2)[0]}-{j['id'].split('-',2)[1]}.wav"})
            cursor += samples
        groups.append({'id': gid, 'duration': cursor / 16000, 'jobs': rows,
                       'voice': voice, 'export_name': gid + '__' + voice + '.wav'})
    result={'version': 1, 'sample_rate':16000, 'groups':groups}
    vc.write_json(plan, result)
    return result


def inputs(batch, group):
    plan = prepare(batch)
    g = next(g for g in plan['groups'] if g['id'] == group)
    folder = batch / 'groups' / group
    folder.mkdir(exist_ok=True)
    def make(row):
        source = Path(row['source'])
        if vc.digest(source) != row['source_sha256']:
            raise ValueError('Source changed: ' + row['job'])
        target = folder / row['file']
        if not target.exists():
            subprocess.run(['ffmpeg','-v','error','-nostdin','-n','-i',str(source),
                '-vn','-af','apad','-t',str(row['duration']),'-ac','1','-ar','16000',
                '-c:a','pcm_s16le',str(target)],check=True)
        if abs(vc.probe(target)['duration'] - row['duration']) > .001:
            raise ValueError('Wrong prepared input duration')
        return row['job']
    with ThreadPoolExecutor(max_workers=4) as pool:
        done = list(pool.map(make,g['jobs']))
    print(json.dumps({'group':group,'inputs':len(done),'duration':g['duration'],
                      'directory':str(folder.resolve())}))


def split(batch, group):
    plan = prepare(batch)
    g = next(g for g in plan['groups'] if g['id'] == group)
    source = batch / 'exports' / g['export_name']
    delta = vc.probe(source)['duration'] - g['duration']
    if abs(delta) > .1:
        raise ValueError('Group duration differs: verify timeline order/length')
    jobs = {j['id']:j for j in json.loads((batch/'queue.json').read_text())['jobs']}
    for row in g['jobs']:
        j = jobs[row['job']]
        target = batch / 'exports' / j['export_name']
        if target.exists():
            raise ValueError('Refuse to overwrite existing page export: '+j['id'])
    export_hash = vc.digest(source)
    for row in g['jobs']:
        j = jobs[row['job']]
        target = batch / 'exports' / j['export_name']
        # Group start/end is an exact 100 ms boundary, independent of GUI frame rounding.
        subprocess.run(['ffmpeg','-v','error','-nostdin','-n',
            '-ss',str(row['start_sample']/16000),'-i',str(source),'-t',str(j['duration']),
            '-ac','1','-ar','16000','-c:a','pcm_s16le',str(target)],check=True)
        report = vc.inspect_export(argparse.Namespace(batch=batch,job=j['id']))
        vc.write_json(batch/'reports'/(j['id']+'__group-provenance.json'),
            {'group':group,'group_sha256':export_hash,'start_sample':row['start_sample'],
             'source_sha256':row['source_sha256'],'export_sha256':report['export_sha256']})
    print('Split',group)


def review(batch, group):
    import voice_conversion_integrity as integrity
    g=next(g for g in prepare(batch)['groups'] if g['id']==group)
    results=[]
    for row in g['jobs']:
        jid=row['job']
        folder=batch/'staged-preserved-v1'/jid
        with contextlib.redirect_stdout(io.StringIO()):
            result=integrity.review(batch,jid,'preserved-v1' if folder.exists() else None)
            if result['passed'] and not folder.exists():
                vc.cut(argparse.Namespace(batch=batch,job=jid,timing_reviewed=True,
                    offset_ms=result['timing']['median_lag_ms'],variant='preserved-v1',
                    conversion_only=True))
                result=integrity.review(batch,jid,'preserved-v1')
        summary={k:result[k] for k in ['job','passed','checked','new_loss','untreated_input_suspected']}
        results.append(summary)
        print(json.dumps(summary,ensure_ascii=False),flush=True)
    vc.write_json(batch/'reports'/(group+'__conversion-summary.json'),{'group':group,'jobs':results})


def repair_plan(batch):
    jobs=json.loads((batch/'queue.json').read_text())['jobs']
    new=[]
    for parent in list(jobs):
        if parent['kind']=='repair':
            continue
        variants=[batch/'reports'/(parent['id']+'__preserved-v1__conversion-integrity.json'),
                  batch/'reports'/(parent['id']+'__conversion-integrity.json')]
        file=next((p for p in variants if p.exists()),None)
        if not file:
            continue
        r=json.loads(file.read_text())
        if r['passed']:
            continue
        if r.get('untreated_input_suspected') or not r['file_integrity']:
            print('Needs full export verification:',parent['id'])
            continue
        if vc.digest(Path(parent['source'])) != parent['source_sha256']:
            raise ValueError('Repair parent source changed')
        intervals=[(c['source_start'],c['source_end']) for c in r['new_loss']]
        timing=r['timing']
        if not timing['stable']:
            median=timing.get('median_lag_ms',0)
            intervals += [(w['source_start'],w['source_start']+8)
                for w in timing.get('windows',[]) if w['correlation']<.65 or abs(w['lag_ms']-median)>60]
        ranges=[]
        for lo,hi in sorted(intervals):
            lo=max(0,lo-5);hi=min(parent['duration'],max(hi+5,lo+14))
            lo=max(0,min(lo,hi-14))
            if ranges and lo<=ranges[-1][1]+2:
                ranges[-1]=(ranges[-1][0],max(hi,ranges[-1][1]))
            else:ranges.append((lo,hi))
        for lo,hi in ranges:
            prior=[j for j in jobs if j.get('parent_job')==parent['id']
                   and j.get('source_origin_seconds')==lo and j.get('duration')==round(hi-lo,6)]
            if prior:
                continue
            jid=f'repair-{len([j for j in jobs if j["kind"]=="repair"])+1:04}'
            source=batch/'inputs'/(jid+'.wav')
            subprocess.run(['ffmpeg','-v','error','-nostdin','-n','-ss',str(lo),
                '-i',parent['source'],'-t',str(hi-lo),'-ac','1','-ar','16000',
                '-c:a','pcm_s16le',str(source)],check=True)
            clips=[{**c,'start':c['start']-lo,'end':c['end']-lo}
                   for c in parent['clips'] if lo<=c['start']<c['end']<=hi]
            if not clips:
                raise ValueError('Repair interval contains no complete practice clips')
            job={'id':jid,'kind':'repair','parent_job':parent['id'],
                'source_origin_seconds':lo,'source':str(source.resolve()),
                'source_sha256':vc.digest(source),'duration':round(hi-lo,6),
                'clips':clips,'voice':parent['voice'],'export_name':jid+'__'+parent['voice']+'.wav'}
            jobs.append(job);new.append(job)
    if not new:
        print('No new local repair inputs required');return
    old=batch/'queue.json'
    backup=batch/('queue-before-'+new[0]['id']+'.json')
    backup.write_bytes(old.read_bytes())
    vc.write_json(old,{'version':1,'jobs':jobs})
    plan=prepare(batch);existing=plan['groups']
    for i in range(0,len(new),30):
        gid=f'group-{max((int(g["id"].split("-")[1]) for g in existing),default=1)+1:03}'
        cursor=0;rows=[]
        for j in new[i:i+30]:
            duration=math.ceil(j['duration']*10)/10
            rows.append({'job':j['id'],'source':j['source'],'source_sha256':j['source_sha256'],
                'duration':duration,'samples':round(duration*16000),'start_sample':cursor,
                'file':gid+'__'+j['id']+'.wav'})
            cursor+=round(duration*16000)
        existing.append({'id':gid,'duration':cursor/16000,'jobs':rows,
            'voice': new[i]['voice'],
            'export_name':gid+'__'+new[i]['voice']+'.wav','kind':'repair'})
    vc.write_json(batch/'groups/plan.json',plan)
    print('Prepared local repairs:',len(new),'; new groups:',[g['id'] for g in existing if g.get('kind')=='repair'])


def assemble(batch):
    import voice_conversion_integrity as integrity
    jobs=json.loads((batch/'queue.json').read_text())['jobs']
    for parent in jobs:
        if parent['kind']=='repair' or (batch/'staged-preserved-v1'/parent['id']).exists():
            continue
        valid=[]
        for j in jobs:
            if j.get('parent_job')!=parent['id']:
                continue
            path=batch/'reports'/(j['id']+'__conversion-integrity.json')
            if path.exists() and json.loads(path.read_text())['passed']:
                valid.append(j['id'])
        if not valid:
            continue
        with contextlib.redirect_stdout(io.StringIO()):
            report=vc.inspect_export(argparse.Namespace(batch=batch,job=parent['id']))
            vc.cut(argparse.Namespace(batch=batch,job=parent['id'],timing_reviewed=True,
                offset_ms=report['timing']['median_lag_ms'],variant='preserved-v1',
                conversion_only=True,repair=valid))
            result=integrity.review(batch,parent['id'],'preserved-v1')
        print(json.dumps({'job':parent['id'],'repairs':valid,'passed':result['passed'],
                         'new_loss':result['new_loss']},ensure_ascii=False),flush=True)


def release(batch):
    jobs=[j for j in json.loads((batch/'queue.json').read_text())['jobs'] if j['kind']!='repair']
    pending=[];mapping={};reviews={}
    for j in jobs:
        folder=batch/'staged-preserved-v1'/j['id']
        manifest=folder/'manifest.json'
        review_file=batch/'reports'/(j['id']+'__preserved-v1__conversion-integrity.json')
        if not manifest.exists() or not review_file.exists():
            pending.append(j['id']);continue
        r=json.loads(review_file.read_text())
        if not r['passed'] or r.get('manifest_sha256')!=vc.digest(manifest):
            pending.append(j['id']);continue
        if r['export_sha256']!=vc.digest(batch/'exports'/j['export_name']):
            raise ValueError('Export changed since review: '+j['id'])
        if vc.digest(Path(j['source']))!=j['source_sha256']:
            raise ValueError('Original changed since queue: '+j['id'])
        reviews[j['id']]={'report_sha256':vc.digest(review_file),
                          'manifest_sha256':r['manifest_sha256'],
                          'export_sha256':r['export_sha256']}
        m=json.loads(manifest.read_text())
        expected={c['id']:c for c in j['clips']}
        if len(m['clips'])!=len(expected) or {c['id'] for c in m['clips']}!=set(expected):
            raise ValueError('Clip set mismatch: '+j['id'])
        for c in m['clips']:
            if c['id'] in mapping:
                raise ValueError('Duplicate ID in release: '+c['id'])
            path=vc.safe_path(folder,c['relative_path'])
            if any(c[k]!=expected[c['id']][k] for k in ['relative_path','start','end']):
                raise ValueError('Original mapping changed: '+c['id'])
            if vc.digest(path)!=c['sha256']:
                raise ValueError('Candidate changed since review: '+c['id'])
            mapping[c['id']]={'job':j['id'],'kind':j['kind'],'voice':j['voice'],
                'original_relative_path':c['relative_path'],
                'replacement':str(path.resolve()),'sha256':c['sha256'],'audio':c['audio']}
    if pending:
        raise ValueError(f'Release incomplete: {len(pending)} jobs remain; first: {pending[:5]}')
    target=batch/'release-preserved-v1.json'
    if target.exists():
        raise ValueError('Release manifest already exists; do not overwrite')
    vc.write_json(target,{'version':1,'scope':'new conversion loss only; inherited corpus issues deferred',
        'jobs':len(jobs),'clip_count':len(mapping),'clips':mapping,'reviewed_jobs':reviews})
    print('Release ready:',len(jobs),'jobs;',len(mapping),'clips;',target.resolve())


def validated_release(batch, data_root):
    data_root=data_root.resolve()
    manifest=(batch/'release-preserved-v1.json').resolve()
    manifest_relative=str(manifest.relative_to(data_root))
    release_data=json.loads(manifest.read_text())
    jobs=[j for j in json.loads((batch/'queue.json').read_text())['jobs'] if j['kind']!='repair']
    expected={c['id']:(j,c) for j in jobs for c in j['clips']}
    if release_data['jobs']!=len(jobs) or set(release_data['clips'])!=set(expected):
        raise ValueError('Release does not cover the complete current queue')
    for j in jobs:
        if vc.digest(Path(j['source']))!=j['source_sha256']:
            raise ValueError('Original changed before activation: '+j['id'])
        review_file=batch/'reports'/(j['id']+'__preserved-v1__conversion-integrity.json')
        record=release_data.get('reviewed_jobs',{}).get(j['id'])
        if not record or record['report_sha256']!=vc.digest(review_file):
            raise ValueError('Release approval changed: '+j['id'])
        candidate=batch/'staged-preserved-v1'/j['id']/'manifest.json'
        if record['manifest_sha256']!=vc.digest(candidate):
            raise ValueError('Candidate manifest changed: '+j['id'])
    for key,entry in release_data['clips'].items():
        job,clip=expected[key]
        if (entry['kind']!=job['kind'] or entry['voice']!=job['voice']
                or entry['original_relative_path']!=clip['relative_path']):
            raise ValueError('Release mapping mismatch: '+key)
        path=vc.safe_path(data_root,entry['replacement'])
        if vc.digest(path)!=entry['sha256']:
            raise ValueError('Release audio changed: '+key)
    return manifest_relative, release_data


def write_active(data_root, pointer):
    active=data_root.resolve()/'derived/voice-conversion/active.json'
    if active.exists():
        backup=active.with_name('active-before-'+vc.digest(active)[:16]+'.json')
        if not backup.exists():
            backup.write_bytes(active.read_bytes())
    vc.write_json(active,pointer)
    print('Activated complete library:',active)


def activate(batch, data_root):
    relative, release_data = validated_release(batch, data_root)
    voices = {entry['voice'] for entry in release_data['clips'].values()}
    if len(voices) != 1:
        raise ValueError('A release must contain exactly one voice')
    write_active(data_root, {'version':1,'manifest':relative,'voice':next(iter(voices)),
                            'sha256':vc.digest(data_root.resolve()/relative)})


def activate_pair(batch, other_batch, data_root):
    voices = {}
    mapping = None
    for folder in (batch, other_batch):
        relative, release_data = validated_release(folder, data_root)
        entries = release_data['clips']
        voice_set = {entry['voice'] for entry in entries.values()}
        if len(voice_set) != 1:
            raise ValueError('A release must contain exactly one voice')
        voice = next(iter(voice_set))
        if voice in voices:
            raise ValueError('Duplicate voice release')
        current = {key: (entry['kind'],entry['original_relative_path'])
                   for key, entry in entries.items()}
        if mapping is not None and current != mapping:
            raise ValueError('Voice releases cover different original clips')
        mapping = current
        voices[voice] = {'manifest':relative,
                        'sha256':vc.digest(data_root.resolve()/relative)}
    if set(voices) != {'news-female','news-male'}:
        raise ValueError('Complete news female and male releases are required')
    write_active(data_root, {'version':2,'default_voice':'news-female','voices':voices})


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--batch',type=Path,required=True)
    p.add_argument('command',choices=['plan','inputs','split','review','repairs','assemble','release','activate','activate-pair','clone-voice'])
    p.add_argument('--group')
    p.add_argument('--data-root',type=Path)
    p.add_argument('--other-batch',type=Path)
    p.add_argument('--voice',choices=['news-female','news-male'])
    a=p.parse_args()
    if a.command=='clone-voice':
        if a.other_batch is None or a.voice is None:p.error('clone-voice requires --other-batch and --voice')
        clone_voice(a.batch,a.other_batch,a.voice)
    elif a.command=='plan': print(json.dumps(prepare(a.batch),ensure_ascii=False))
    elif a.command=='inputs':inputs(a.batch,a.group)
    elif a.command=='split':split(a.batch,a.group)
    elif a.command=='review':review(a.batch,a.group)
    elif a.command=='repairs':repair_plan(a.batch)
    elif a.command=='assemble':assemble(a.batch)
    elif a.command=='release':release(a.batch)
    elif a.data_root is None:p.error('activate requires --data-root')
    elif a.command=='activate-pair':
        if a.other_batch is None:p.error('activate-pair requires --other-batch')
        activate_pair(a.batch,a.other_batch,a.data_root)
    else:activate(a.batch,a.data_root)
