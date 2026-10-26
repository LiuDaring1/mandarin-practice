from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from select_nasal_encoder import choose


def candidate(name,accuracy,detected,fp=0):
    return {'directory':name,'selection':{
        'dataset_sha256':'same-dataset','train_ids':['train'],'dev_ids':['dev'],
        'review_margin':.2,'selected':{'dev_balanced_accuracy':accuracy},
        'development_margin_table':[{'margin':.2,'correct_error_directions':detected,'false_nasal_accusations':fp}]}}


def test_selection_prioritizes_useful_development_directions_without_false_accusations():
    ranking=choose([candidate('higher-accuracy',.99,5,2),candidate('fewer-false-accusations',.93,3)])
    assert ranking[0]['directory']=='fewer-false-accusations'


def test_different_data_or_speaker_partitions_are_not_comparable():
    for field,value in [('dataset_sha256','different'),('train_ids',['different']),('dev_ids',['different'])]:
        one=candidate('one',.9,3);two=candidate('two',.9,3)
        two['selection'][field]=value
        with pytest.raises(ValueError,match='different'):
            choose([one,two])
