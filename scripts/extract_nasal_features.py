"""Cache pooled frozen-encoder features; expected text never enters inference."""
from collections import defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import wave

import numpy as np

from nasal_acoustics import AcousticModel, read_audio
from nasal_feature_probe import LAYERS, REGIONS, acoustic_window, pool_regions
from nasal_window import convolution_geometry


def main(args):
    import torch
    folder = Path(args.directory)
    dataset = json.loads((folder/'dataset.json').read_text())
    groups = defaultdict(list)
    for row in dataset['rows']:
        groups[row['audio']].append(row)
    cache = Path(args.cache_dir) if args.cache_dir else folder/'features'
    cache.mkdir(parents=True, exist_ok=True)
    model = AcousticModel(args.model)
    encoder = model.model.wav2vec2 if args.model == 'phoneme' else model.model.encoder
    field,stride=convolution_geometry(encoder.config.conv_kernel,encoder.config.conv_stride)
    if max(LAYERS)>encoder.config.num_hidden_layers:
        raise ValueError('Selected layer is not present in the pinned encoder')
    output, excluded = [], []
    for audio, rows in groups.items():
        audio_sha = hashlib.sha256(Path(audio).read_bytes()).hexdigest()
        if any(r['audio_sha256'] != audio_sha for r in rows):
            raise ValueError('Audio changed after dataset freeze')
        with wave.open(audio,'rb') as wav:
            if (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())!=(16000,1,2):
                raise ValueError('Feature manifests require 16 kHz mono PCM16 WAV')
            sample_count=wav.getnframes()
        chunks=defaultdict(list);rejected=[]
        for row in rows:
            try:
                window=acoustic_window(row['bounds'],sample_count)
            except ValueError as error:
                rejected.append({'id':row['id'],'reason':str(error)})
                continue
            chunks[window].append(row)
        identity = {'audio_sha256':audio_sha, 'model':model.spec, 'layers':LAYERS, 'regions':REGIONS,
                    'targets':[(r['id'],r['bounds']) for r in rows], 'preprocessing':'normalized-pcm16k-mean-pool-v1'}
        if sample_count>16000*60:
            identity['preprocessing']='normalized-pcm16k-windows45s-step40s-pool-v2'
            identity['windows']=[(list(window),[r['id'] for r in selected]) for window,selected in chunks.items()]
        key = hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
        path = cache/(key+'.npz')
        meta_path = cache/(key+'.json')
        if not path.exists() or not meta_path.exists():
            samples = read_audio(Path(audio),max_seconds=180)
            by_id={}
            for (start,end),chunk_rows in chunks.items():
                inputs = model.extractor(samples[start:end],sampling_rate=16000,return_tensors='pt')
                with torch.inference_mode():
                    states = encoder(**{k:v.to('mps') for k,v in inputs.items()},
                                     output_hidden_states=True).hidden_states
                    selected = {layer:states[layer][0].float().cpu().numpy() for layer in LAYERS}
                for row in chunk_rows:
                    bounds={name:[t-start/16000 for t in limits] for name,limits in row['bounds'].items()}
                    try:
                        vector = np.stack([pool_regions(selected[layer],bounds,sample_count=end-start,
                                                        stride=stride,receptive_field=field) for layer in LAYERS])
                    except ValueError as error:
                        rejected.append({'id':row['id'],'reason':str(error)})
                        continue
                    by_id[row['id']]=vector
                del states, selected, inputs
                torch.mps.empty_cache()
            valid=[r['id'] for r in rows if r['id'] in by_id]
            vectors=[by_id[uid] for uid in valid]
            arrays = np.stack(vectors) if vectors else np.empty((0,len(LAYERS),len(REGIONS),1024),dtype=np.float32)
            temporary = path.with_suffix('.tmp.npz')
            np.savez_compressed(temporary,features=arrays,ids=np.array(valid,dtype=str))
            temporary.chmod(0o600);temporary.replace(path)
            meta_path.write_text(json.dumps({'identity':identity,'excluded':rejected},ensure_ascii=False,indent=2))
            meta_path.chmod(0o600)
        with np.load(path,allow_pickle=False) as data:
            output.extend({'id':str(identity),'cache':str(path),'index':i} for i,identity in enumerate(data['ids']))
        excluded.extend(json.loads(meta_path.read_text())['excluded'])
        print('audio',len(output),'targets cached',flush=True)
    report = {'complete':True,'model':model.spec,'layers':LAYERS,'regions':REGIONS,
              'dataset_sha256':hashlib.sha256((folder/'dataset.json').read_bytes()).hexdigest(),
              'rows':output,'excluded':excluded}
    path=folder/'feature-index.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2));path.chmod(0o600)
    print('COMPLETE',len(output),'EXCLUDED',len(excluded),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',default='data/derived/nasal-acoustic-validation/feature-classifier-v1')
    parser.add_argument('--cache-dir')
    parser.add_argument('--model',choices=['final','phoneme'],default='final')
    main(parser.parse_args())
