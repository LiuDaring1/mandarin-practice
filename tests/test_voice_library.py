import json
from pathlib import Path

import pytest

from pth_corpus.voice_library import VoiceLibrary, file_digest


def activate(root, replacement, *, original='derived/word.wav', kind='word'):
    manifest=root/'derived/voice-conversion/test-release.json'
    manifest.parent.mkdir(parents=True,exist_ok=True)
    manifest.write_text(json.dumps({'version':1,'clip_count':1,'clips':{'t1-00001':{
        'kind':kind,'original_relative_path':original,'replacement':str(replacement),
        'sha256':file_digest(replacement)}}}))
    pointer=manifest.parent/'active.json'
    pointer.write_text(json.dumps({'version':1,'manifest':str(manifest.relative_to(root)),
                                  'sha256':file_digest(manifest)}))
    return manifest,pointer


def test_missing_library_retains_original_routing(tmp_path):
    library=VoiceLibrary(tmp_path)
    assert library.replacement('t1-00001','word',tmp_path/'derived/word.wav') is None
    assert library.status()=={'active':False,'version':None,'clip_count':0,'error':None}


def test_atomic_activation_rollback_and_clip_hash_guard(tmp_path):
    replacement=tmp_path/'replacement.wav';replacement.write_bytes(b'converted')
    library=VoiceLibrary(tmp_path)
    _,pointer=activate(tmp_path,replacement)
    original=tmp_path/'derived/word.wav'
    assert library.replacement('t1-00001','word',original)==replacement
    replacement.write_bytes(b'changed')
    assert library.replacement('t1-00001','word',original) is None
    assert 'hash mismatch' in library.status()['error']
    pointer.rename(pointer.with_suffix('.saved'))
    assert not library.status()['active']


@pytest.mark.parametrize('kind,original', [('sentence','derived/word.wav'),
                                         ('word','derived/different.wav')])
def test_wrong_kind_or_original_mapping_is_rejected(tmp_path,kind,original):
    replacement=tmp_path/'replacement.wav';replacement.write_bytes(b'converted')
    activate(tmp_path,replacement,kind=kind,original=original)
    library=VoiceLibrary(tmp_path)
    assert library.replacement('t1-00001','word',tmp_path/'derived/word.wav') is None
    assert 'mapping mismatch' in library.status()['error']


def test_outside_and_symlink_replacements_are_rejected(tmp_path):
    root=tmp_path/'data';root.mkdir()
    outside=tmp_path/'private.wav';outside.write_bytes(b'outside data root')
    for path in [outside,root/'link.wav']:
        if path!=outside:path.symlink_to(outside)
        activate(root,path)
        assert VoiceLibrary(root).replacement('t1-00001','word',root/'derived/word.wav') is None


def test_manifest_tampering_invalidates_cached_library(tmp_path):
    replacement=tmp_path/'replacement.wav';replacement.write_bytes(b'converted')
    manifest,_=activate(tmp_path,replacement)
    library=VoiceLibrary(tmp_path)
    assert library.status()['active']
    manifest.write_text(manifest.read_text()+' ')
    assert not library.status()['active']
    assert 'manifest hash mismatch' in library.status()['error']
