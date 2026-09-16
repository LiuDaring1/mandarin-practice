"""Index the author's unmodified CC0 WAVs. Does not synthesize or process audio."""
from pathlib import Path
import hashlib, json, wave, zipfile
import numpy as np

LAB=Path(__file__).resolve().parents[1]
PACK=LAB/'external/dustyroom'
records=[]
with zipfile.ZipFile(PACK/'DM-CGS.zip') as archive:
    for path in sorted(PACK.glob('DM-CGS-*.wav')):
        original=archive.read('DM-CGS/WAV/'+path.name)
        assert path.read_bytes()==original, path.name
        with wave.open(str(path)) as w:
            channels,width,rate,frames=w.getnchannels(),w.getsampwidth(),w.getframerate(),w.getnframes()
            assert (channels,width,rate)==(2,3,44100)
            data=np.frombuffer(w.readframes(frames),dtype=np.uint8).reshape(-1,3).astype(np.int32)
            pcm=data[:,0] | (data[:,1]<<8) | (data[:,2]<<16)
            pcm=np.where(pcm>=8388608,pcm-16777216,pcm)/8388608
        peak=float(np.max(np.abs(pcm)))
        records.append(dict(number=int(path.stem[-2:]),url='/external/dustyroom/'+path.name,
            duration=frames/rate,channels=channels,bit_depth=24,sample_rate=rate,
            sample_peak_dbfs=round(20*np.log10(max(peak,1e-12)),3),
            samples_at_full_scale=int(np.sum(np.abs(pcm)>=1)),
            sha256=hashlib.sha256(original).hexdigest(),unmodified_from_zip=True))
assert len(records)==50
extra=[]
rp=LAB/'external/r4orce'
labels=['可爱轻点','柔软点击','小泡泡','轻盈弹出','小闪光','气泡轻点','轻点铃音','魔法闪烁','羽毛轻点','数字短音','成功短音','错误短音','滑动','菜单打开','菜单关闭','通知','提醒','轻提示','开关开启','开关关闭','奖励短音','悬停','返回','勾选','进度完成','收集','金币收集','解锁','升级','升级完成','拖动','放下','吸附','选中','取消选中','加载','额外奖励','连击','柔和失败','检查点']
with zipfile.ZipFile(rp/'Cute-UI-Sound-Pack.zip') as archive:
    for path in sorted(rp.glob('*.wav')):
        b=archive.read('Cute - UI Sound Pack/WAV_48kHz_24bit/'+path.name)
        assert path.read_bytes()==b
        with wave.open(str(path)) as w:
            assert (w.getnchannels(),w.getsampwidth(),w.getframerate())==(1,3,48000)
            duration=w.getnframes()/w.getframerate()
        num=int(path.name[:2])
        extra.append(dict(number=100+num,source_number=num,label=labels[num-1],url='/external/r4orce/'+path.name,
            duration=duration,channels=1,bit_depth=24,sample_rate=48000,sha256=hashlib.sha256(b).hexdigest(),unmodified_from_zip=True))
assert len(extra)==40
manifest=dict(version='sound-library-free-only-2026-09-12-v3',author='Dustyroom',
    source='https://dustyroom.com/free-casual-game-sounds/',
    download='https://dustyroom.com/casualgamesounds/DM-CGS.zip',
    license='CC0',license_file='/external/dustyroom/LICENSE.txt',
    archive_sha256=hashlib.sha256((PACK/'DM-CGS.zip').read_bytes()).hexdigest(),
    processing='None. Source WAVs are byte-identical to the author ZIP. Playback volume only.',
    listening_status='Not ear-audited by assistant; user audition required. No formal event mapping selected.',
    preview_numbers=[2,7,5,23,11,49],samples=records,
    extra_source=dict(author='R4orce',source='https://r4orce.itch.io/cute-ui-sound-pack',acquisition='Official name-your-price free download, no payment',
        license='Personal and commercial project use allowed; no resale or public raw-file redistribution',license_file='/external/r4orce/License.txt',
        archive_sha256=hashlib.sha256((rp/'Cute-UI-Sound-Pack.zip').read_bytes()).hexdigest()),extra_samples=extra)
(LAB/'library-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
(LAB/'qa/library-v3/audio-source-report.json').write_text(json.dumps(dict(files=50,
    byte_identical_to_archive=True,peak_range_dbfs=[min(r['sample_peak_dbfs'] for r in records),max(r['sample_peak_dbfs'] for r in records)],
    sample_full_scale_count=sum(r['samples_at_full_scale'] for r in records),
    machine_checks_only=True,samples=records,additional_files=40,additional_byte_identical_to_archive=True,extra_samples=extra),ensure_ascii=False,indent=2)+'\n')
print('Indexed 50 CC0 stereo WAVs + 40 free licensed mono WAVs; all byte-identical, no audio processing.')
