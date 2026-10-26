"""Fetch a pinned, audio-only Mandarin encoder into ignored research storage."""
import hashlib
import json
from pathlib import Path

from train_nasal_feature_probe import save_json

REPOSITORY = 'TencentGameMate/chinese-hubert-large'
REVISION = '90cb660492214f687e60f5ca509b20edae6e75bd'
FOLDER = Path('data/derived/nasal-acoustic-validation/chinese-hubert-model-v1')
FILES = ('README.md', 'config.json', 'preprocessor_config.json', 'pytorch_model.bin')


def main():
    from huggingface_hub import HfApi, hf_hub_download
    if (FOLDER / 'source.json').exists():
        raise ValueError('Model source already frozen')
    info = HfApi().model_info(REPOSITORY, revision=REVISION, files_metadata=True)
    if info.sha != REVISION or info.gated or info.card_data.get('license') != 'mit':
        raise ValueError('Unexpected source identity/access/license')
    available = {s.rfilename: s for s in info.siblings}
    sources = {}
    for name in FILES:
        path = Path(hf_hub_download(REPOSITORY, name, revision=REVISION, local_dir=FOLDER))
        body = path.read_bytes(); digest = hashlib.sha256(body).hexdigest(); source = available[name]
        if len(body) != source.size:
            raise ValueError('Source size mismatch')
        if source.lfs:
            if digest != source.lfs.sha256: raise ValueError('Source LFS digest mismatch')
        elif hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest() != source.blob_id:
            raise ValueError('Source Git blob mismatch')
        path.chmod(0o600)
        sources[str(path)] = {'sha256': digest, 'bytes': len(body), 'git_blob': source.blob_id}
        print('VERIFIED', name, len(body), flush=True)
    save_json(FOLDER / 'source.json', {'repository': REPOSITORY, 'revision': REVISION, 'license': 'mit',
        'sources': sources, 'remote_code': False, 'weight_loading': 'torch weights_only=True',
        'reference': 'https://huggingface.co/' + REPOSITORY + '/tree/' + REVISION})
    print('MODEL SOURCE COMPLETE', flush=True)


if __name__ == '__main__': main()
