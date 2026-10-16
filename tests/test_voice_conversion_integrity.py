import importlib.util
from pathlib import Path
import sys

import numpy as np

scripts=Path(__file__).parents[1]/'scripts'
sys.path.insert(0,str(scripts))
spec=importlib.util.spec_from_file_location('voice_conversion_integrity',scripts/'voice_conversion_integrity.py')
integrity=importlib.util.module_from_spec(spec)
spec.loader.exec_module(integrity)


def speech():
    t=np.arange(32000)/16000
    a=.15*np.sin(2*np.pi*220*t)*(0.6+0.4*np.sin(2*np.pi*3*t)**2)
    a[:1600]=0;a[-1600:]=0
    return a


def test_inherited_silence_is_not_new_loss():
    clip={'id':'old','start':0,'end':2}
    row=integrity.compare_clip(clip,np.zeros(32000),np.zeros(32000))
    assert row['source_silent'] and not row['new_loss']


def test_gain_and_old_clipped_boundaries_do_not_block_conversion():
    a=speech()[4000:24000]
    row=integrity.compare_clip({'id':'old-cut','start':.25,'end':1.5},a,a*.3)
    assert not row['new_loss']


def test_partial_new_missing_vowel_is_detected():
    a=speech();b=a*.5;b[8000:14400]=0
    row=integrity.compare_clip({'id':'partial','start':0,'end':2},a,b)
    assert row['new_loss'] and not row['converted_silent']
    assert row['missing_intervals'][0]['end']-row['missing_intervals'][0]['start']>=.3


def test_existing_pause_is_allowed_but_new_truncation_is_rejected():
    a=speech();a[8000:14400]=0
    clip={'id':'pause','start':0,'end':2}
    assert not integrity.compare_clip(clip,a,a*.7)['new_loss']
    assert integrity.compare_clip(clip,a,a[:-1600])['truncated']


def test_complete_new_silence_is_detected():
    row=integrity.compare_clip({'id':'lost','start':0,'end':2},speech(),np.zeros(32000))
    assert row['new_loss'] and row['converted_silent']


def test_untreated_export_is_detected_despite_delay_and_gain():
    rng=np.random.default_rng(7)
    source=rng.normal(0,.06,16000*12)
    converted=np.r_[np.zeros(1120),source[:-1120]]*.7
    assert integrity.unchanged_waveform(source,converted)
    assert not integrity.unchanged_waveform(source,rng.normal(0,.06,len(source)))
