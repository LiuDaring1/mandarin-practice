"""Pinned, locally audited PhoneticXeus research inference, never a grade.

Weights are CC BY-NC-SA 4.0 and stay in the private research cache. The upstream
architecture is kept intact. Three optional torchaudio imports are made lazy
in a private source copy because waveform decoding here uses FFmpeg instead.
"""
import ast
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import time

import numpy as np

from fetch_phonetic_xeus import FOLDER, REVISION, sha256
from nasal_acoustics import greedy_spans
from nasal_window import convolution_geometry

LAZY_FILES = frozenset(['pxeus/core/utils.py', 'pxeus/model/xeusphoneme/xeuspr_model.py',
                        'pxeus/model/xeusphoneme/xeuspr_inference.py'])


def lazy_audio_import(source):
    tree = ast.parse(source)
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.Import)
               and any(alias.name == 'torchaudio' for alias in node.names)]
    if len(imports) != 1 or len(imports[0].names) != 1 or imports[0].names[0].asname:
        raise ValueError('Unexpected optional audio import shape')
    replacement = ('def _optional_torchaudio():\n'
                   '    import torchaudio\n'
                   '    return torchaudio\n')
    lines = source.splitlines(keepends=True)
    lines[imports[0].lineno-1] = '\n'
    insert_at = tree.body[0].end_lineno if ast.get_docstring(tree) is not None else 0
    lines.insert(insert_at, '\n'+replacement+'\n')
    result = ''.join(lines).replace('torchaudio.', '_optional_torchaudio().')
    ast.parse(result)
    return result


def prepare_runtime():
    provenance = json.loads((FOLDER / 'model-source.json').read_text())
    if provenance['revision'] != REVISION:
        raise ValueError('Unexpected PhoneticXeus revision')
    root = FOLDER / 'runtime'; root.mkdir(exist_ok=True)
    files = []; weights = None
    for record in provenance['files']:
        source = Path(record['path'])
        if sha256(source) != record['sha256']:
            raise ValueError('Pinned upstream file changed')
        if record['file'] == 'model.safetensors':
            weights = source
            continue
        content = source.read_text()
        if record['file'] in LAZY_FILES:
            content = lazy_audio_import(content)
        target = root / record['file']; target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_text() != content:
            raise ValueError('Private runtime differs from allowlisted import-only patch')
        if not target.exists():
            target.write_text(content); target.chmod(0o600)
        files.append({'file': record['file'], 'upstream_sha256': record['sha256'],
                      'runtime_sha256': sha256(target), 'lazy_audio_import': record['file'] in LAZY_FILES})
    if weights is None:
        raise ValueError('Missing verified safe weights')
    manifest = {'source_manifest_sha256': sha256(FOLDER / 'model-source.json'), 'files': files,
                'model_math_or_parameters_modified': False, 'optional_import_patch': sorted(LAZY_FILES)}
    path = FOLDER / 'runtime-source.json'
    if path.exists() and json.loads(path.read_text()) != manifest:
        raise ValueError('Runtime provenance already frozen differently')
    if not path.exists():
        path.write_text(json.dumps(manifest, indent=2)+'\n'); path.chmod(0o600)
    return root.resolve(), weights


class XeusModel:
    def __init__(self, device='mps'):
        import torch
        from safetensors.torch import load_file

        root, weights = prepare_runtime()
        sys.path.insert(0, str(root))
        from pxeus.model.xeusphoneme.builders import build_xeus_pr_from_hf

        self.device = device
        self.vocab = json.loads((root / 'ipa_vocab.json').read_text())
        self.model = build_xeus_pr_from_hf(work_dir=str(root), hf_repo=None, load_ckpt=False,
            config_file=str(root / 'pxeus/model/xeusphoneme/resources/xeus_config.yaml'),
            vocab_file=str(root / 'ipa_vocab.json'), interctc_layer_idx=[4, 8, 12],
            interctc_use_conditioning=True)
        state = load_file(str(weights))
        if not all(k.startswith('model.') for k in state):
            raise ValueError('Unexpected upstream state namespace')
        self.model.load_state_dict({k.removeprefix('model.'): v for k, v in state.items()}, strict=True, assign=True)
        del state
        self.model.eval().to(device)
        if self.model.encoder.interctc_layer_idx != [4, 8, 12] or self.model.encoder.interctc_use_conditioning is not True:
            raise ValueError('Required self-conditioned CTC is disabled')
        self.conditioning_calls = 0
        self.conditioning_norms = []

        def conditioning_hook(module, inputs, output):
            self.conditioning_calls += 1
            self.conditioning_norms.append(float(output.detach().float().norm().cpu()))

        self.model.encoder.conditioning_layer.register_forward_hook(conditioning_hook)
        kernels = [layer.kernel_size for layer in self.model.frontend.layers]
        strides = [layer.stride for layer in self.model.frontend.layers]
        self.field, self.stride = convolution_geometry(kernels, strides)
        self.identity = {'revision': REVISION, 'weights_sha256': sha256(weights),
                         'runtime_sha256': sha256(FOLDER / 'runtime-source.json'),
                         'dtype': 'float32', 'device': device,
                         'dependencies': {p: importlib.metadata.version(p) for p in ['torch', 'typeguard', 'torch-complex', 'safetensors', 'numpy']},
                         'normalize_audio': self.model.frontend.normalize_audio,
                         'conditioning_layers': [4, 8, 12], 'frame_stride_samples': self.stride,
                         'receptive_field_samples': self.field, 'reference_text_input': False}

    def infer(self, samples, *, cache=True):
        import torch
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1 or not 1600 <= len(samples) <= 20*16000 or not np.isfinite(samples).all():
            raise ValueError('Expected finite 0.1–20 s waveform')
        key = hashlib.sha256(json.dumps(self.identity, sort_keys=True).encode()+samples.tobytes()).hexdigest()
        root = FOLDER / 'cache'; root.mkdir(exist_ok=True)
        path = root / (key+'.npz')
        if cache and path.exists():
            with np.load(path, allow_pickle=False) as data:
                return {'logits': data['logits'], 'key': key, 'conditioning_calls': int(data['conditioning_calls']),
                        'conditioning_norms': data['conditioning_norms'].tolist(), 'elapsed_seconds': float(data['elapsed_seconds'])}
        speech = torch.from_numpy(samples.copy()).unsqueeze(0).to(self.device)
        lengths = torch.tensor([len(samples)], dtype=torch.long, device=self.device)
        self.conditioning_calls = 0; self.conditioning_norms = []
        started = time.monotonic()
        with torch.inference_mode():
            encoded, output_lengths = self.model.encode(speech, lengths)
            if isinstance(encoded, tuple):
                encoded = encoded[0]
            logits = self.model.ctc.ctc_lo(encoded)[0].float().cpu().numpy()
        elapsed = time.monotonic()-started
        expected = (len(samples)-self.field)//self.stride+1
        if self.conditioning_calls != 3 or not all(np.isfinite(n) and n > 0 for n in self.conditioning_norms):
            raise RuntimeError('Self-conditioned CTC did not execute three nonzero updates')
        if int(output_lengths[0]) != expected or logits.shape != (expected, len(self.vocab)) or not np.isfinite(logits).all():
            raise RuntimeError('Unexpected acoustic length, vocabulary or values')
        result = {'logits': logits, 'key': key, 'conditioning_calls': self.conditioning_calls,
                  'conditioning_norms': self.conditioning_norms, 'elapsed_seconds': elapsed}
        if cache:
            temporary = path.with_suffix('.tmp.npz')
            np.savez_compressed(temporary, **{k:v for k,v in result.items() if k != 'key'})
            temporary.chmod(0o600); temporary.replace(path)
        del speech, encoded
        if self.device == 'mps':
            torch.mps.empty_cache()
        return result


def smoke():
    from nasal_acoustics import read_audio
    audio = Path('data/derived/nasal-validation-v2/t1-05280.wav')
    model = XeusModel()
    result = model.infer(read_audio(audio))
    report = {'model': model.identity, 'audio_sha256': sha256(audio),
              'output_shape': list(result['logits'].shape),
              **{k:v for k,v in result.items() if k not in ('logits', 'key')},
              'spans': greedy_spans(result['logits'], model.vocab)}
    output = FOLDER / 'smoke.json'
    if output.exists():
        raise ValueError('Smoke report already exists')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n'); output.chmod(0o600)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    smoke()
