import json
import random

from pth_corpus.news_sentences import load_news_pool, mixed_session


def row(i,genre):
    return {'sentence_id':f'{genre}-{i}','genre':genre,'nasal_density':.4,
            'final_seq':'en ing','label_seq':'FB','front_count':1,'back_count':1,
            'nasal_count':2,'char_count':2}


def test_mixed_sampling_balanced_reproducible_without_duplicates():
    pool=[row(i,genre) for genre in ('news','literature') for i in range(40)]
    result=mixed_session(pool,count=10,filter_mode='all',seed=42)
    assert sum(r['genre']=='news' for r in result)==5
    assert len({r['sentence_id'] for r in result})==10
    assert result==mixed_session(pool,count=10,filter_mode='all',seed=42)
    odd=mixed_session(pool,count=15,filter_mode='all',seed=43)
    assert sum(r['genre']=='news' for r in odd) in (7,8)


def test_shortage_uses_other_source_without_duplicating():
    pool=[row(0,'news')]+[row(i,'literature') for i in range(12)]
    result=mixed_session(pool,count=10,filter_mode='all',seed=2)
    assert len(result)==10 and sum(r['genre']=='news' for r in result)==1


def test_release_requires_every_clip_both_voices_and_safe_path(tmp_path):
    release=tmp_path/'derived/news-sentence-v1/release.json';release.parent.mkdir(parents=True)
    original=tmp_path/'derived/news-sentence-v1/clips/news-2649371281-1-0001.wav'
    original.parent.mkdir();original.write_bytes(b'fixture')
    news={'sentence_id':'news-2649371281-1-0001','original_relative_path':str(original.relative_to(tmp_path))}
    def write():release.write_text(json.dumps({'version':1,'count':1,'sentences':[news]}))
    class Library:
        missing='news-male'
        def replacement(self,sid,kind,path,voice):return path if voice!=self.missing else None
    library=Library();write()
    assert load_news_pool(tmp_path,library)==[]
    library.missing=None
    assert load_news_pool(tmp_path,library)[0]['genre']=='news'
    news['original_relative_path']='../../outside.wav';write()
    assert load_news_pool(tmp_path,library)==[]
