"""Reproduce local import and media QA; animation sources are read-only."""
from pathlib import Path
import hashlib, json, shutil, subprocess, io
from PIL import Image
ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT.parent / 'eng_layered/series'
OUT = Path(__file__).resolve().parent
DEST = ROOT / 'src/pth_corpus/prototype_static/calibration'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
expected = json.loads((SOURCE/'output/media_check.json').read_text())
rows=[]
for sound in ['an','ang','en','eng','in','ing']:
    for mode,label in [('normal','正常版'),('slow','半速版')]:
        source=SOURCE/'交付'/f'{sound}_{label}.mp4'
        digest=sha(source)
        assert digest == expected[sound][label]['sha256'], source
        target=DEST/(f'{sound}.mp4' if mode=='normal' else f'{sound}-slow.mp4')
        metadata=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(source)]))
        video=next(s for s in metadata['streams'] if s['codec_type']=='video')
        audio=[s for s in metadata['streams'] if s['codec_type']=='audio']
        assert (video['width'],video['height'],video['r_frame_rate'])==(1920,1080,'60/1')
        assert len(audio)==(1 if mode=='normal' else 0)
        subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(source),'-f','null','-'],check=True,stdout=subprocess.DEVNULL)
        shutil.copy2(source,target)
        assert sha(target)==digest
        rows.append({'sound':sound,'mode':mode,'source':str(source),'target':str(target.relative_to(ROOT)), 'bytes':target.stat().st_size,'source_sha256':digest,'target_sha256':sha(target),'decode':'passed','metadata':metadata})
    poster=DEST/f'{sound}-poster.webp'
    png=subprocess.check_output(['ffmpeg','-v','error','-ss','0.72','-i',str(DEST/f'{sound}.mp4'),'-frames:v','1','-vf','scale=1280:720','-f','image2pipe','-c:v','png','-'])
    Image.open(io.BytesIO(png)).save(poster,quality=90)
    rows.append({'sound':sound,'mode':'poster','source':f'{sound}.mp4','time_seconds':0.72,'target':str(poster.relative_to(ROOT)), 'bytes':poster.stat().st_size,'sha256':sha(poster),'width':1280,'height':720})
(OUT/'source-manifest.json').write_text(json.dumps({'version':'2026-09-12-series-v2','transcoding':'none; videos copied byte-for-byte','files':rows},ensure_ascii=False,indent=2))
print('PASS: 12 source hashes, full decoding, metadata, copied hashes; 6 posters extracted')
