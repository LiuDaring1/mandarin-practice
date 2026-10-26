"""Download a fixed public research model; never execute its source here."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request

REPO = 'changelinglab/PhoneticXeus'
REVISION = 'ed64f14aeb0e903a80a825cf67a079aa8f93d3ac'
FOLDER = Path('data/derived/nasal-acoustic-validation/xeus-v1')


def sha256(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4*1024*1024), b''):
            value.update(chunk)
    return value.hexdigest()


def main():
    from huggingface_hub import hf_hub_download
    FOLDER.mkdir(exist_ok=True)
    output = FOLDER / 'model-source.json'
    if output.exists():
        raise ValueError('Model provenance already frozen')
    with urllib.request.urlopen(f'https://huggingface.co/api/models/{REPO}/revision/{REVISION}?blobs=true', timeout=30) as response:
        metadata = json.load(response)
    if metadata['sha'] != REVISION:
        raise ValueError('Model revision mismatch')
    # Use the safe tensor serialization only; do not fetch duplicate pickle weights.
    selected = [f for f in metadata['siblings'] if f['rfilename'] in
                ('README.md', 'config.json', 'model.safetensors', 'ipa_vocab.json',
                 'configuration_phoneticxeus.py', 'modeling_phoneticxeus.py') or f['rfilename'].startswith('pxeus/')]

    def download(item):
        name = item['rfilename']
        path = Path(hf_hub_download(REPO, name, revision=REVISION, token=False))
        if path.stat().st_size != item['size']:
            raise ValueError('Downloaded file size mismatch')
        checksum = sha256(path)
        if 'lfs' in item:
            if checksum != item['lfs']['sha256']:
                raise ValueError('Weight checksum mismatch')
        else:
            blob = hashlib.sha1(f'blob {item["size"]}\0'.encode() + path.read_bytes()).hexdigest()
            if blob != item['blobId']:
                raise ValueError('Source Git blob mismatch')
        print('VERIFIED', name, item['size'], flush=True)
        return {'file': name, 'path': str(path), 'bytes': item['size'], 'sha256': checksum}

    small = [f for f in selected if f['rfilename'] != 'model.safetensors']
    with ThreadPoolExecutor(max_workers=4) as pool:
        files = list(pool.map(download, small))
    print('Downloading FP32 weights to the internal Hugging Face cache.', flush=True)
    files.extend(download(f) for f in selected if f['rfilename'] == 'model.safetensors')
    manifest = {'repo': REPO, 'revision': REVISION, 'files': files,
                'license': metadata.get('cardData', {}).get('license'),
                'source_executed': False, 'weights_format': 'safetensors'}
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n'); output.chmod(0o600)
    print('MODEL DOWNLOAD VERIFIED', len(files), flush=True)


if __name__ == '__main__':
    main()
