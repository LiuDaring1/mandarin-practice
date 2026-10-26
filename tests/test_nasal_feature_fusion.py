from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from nasal_feature_fusion import align_features, feature_source, gate_scores
from collect_nasal_backgrounds import CATEGORIES, select_recordings


def row(uid):
    return {'id':uid, 'speaker':'one', 'split':'dev', 'expected_label':'front',
            'actual_label':'back', 'audio_sha256':uid, 'bounds':{'syllable':[0,1], 'vowel':[.2,.8]}}


def test_pairing_uses_identity_instead_of_file_order():
    result = align_features([row('a'),row('b')], [[1,2],[3,4]],
                            [row('b'),row('a')], [[30,40],[10,20]])
    assert feature_source(result,'concatenated').tolist() == [[1,2,10,20],[3,4,30,40]]


@pytest.mark.parametrize('field,value', [('split','train'),('actual_label','front'),
                                       ('bounds',{'syllable':[1,2], 'vowel':[1.2,1.8]})])
def test_disagreeing_target_metadata_cannot_be_fused(field,value):
    other={**row('a'),field:value}
    with pytest.raises(ValueError,match='metadata conflict'):
        align_features([row('a')],[[1,2]],[other],[[3,4]])


def test_duplicate_and_missing_target_identity_are_not_silently_dropped():
    with pytest.raises(ValueError,match='identity'):
        align_features([row('a'),row('a')],[[1,2],[3,4]],[row('a'),row('b')],[[3,4],[5,6]])


def test_absent_phone_evidence_cannot_keep_a_high_confidence_head_claim():
    original=np.array([[30.,0.,0.],[0.,25.,0.]])
    result=gate_scores(original,[False,True])
    assert result.tolist()==[[0.,0.,1.],[0.,25.,0.]]
    assert original[0,0]==30.
    with pytest.raises(ValueError,match='boolean'):gate_scores(original,[0,1])


def test_background_selection_keeps_different_source_files_and_is_order_invariant():
    rows=[{'category':c,'filename':f'{c}-{i}-{take}.wav','src_file':str(i)}
          for c in CATEGORIES for i in range(4) for take in range(2)]
    chosen=select_recordings(rows)
    assert chosen==select_recordings(list(reversed(rows)))
    for category in CATEGORIES:
        subset=[r for r in chosen if r['category']==category]
        assert len(subset)==3 and len({r['src_file'] for r in subset})==3
