"""Additive, local news sentence releases and balanced practice sampling."""
from __future__ import annotations
import json
from pathlib import Path
import random
import re

from .sentence_reading import apply_filter, apply_final_filter, build_session

NEWS_ID = re.compile(r'^news-\d{8,12}-\d{1,2}-\d{4}$')


def load_news_pool(data_root: Path, voice_library) -> list[dict]:
    """Publish only a complete immutable release with both verified voices."""
    path = data_root / 'derived/news-sentence-v1/release.json'
    if not path.exists():
        return []
    try:
        release = json.loads(path.read_text(encoding='utf-8'))
        rows = release['sentences']
        if release['version'] != 1 or release['count'] != len(rows):
            return []
        ids = set()
        for row in rows:
            sid = row['sentence_id']
            if not NEWS_ID.fullmatch(sid) or sid in ids:
                return []
            ids.add(sid)
            original = (data_root / row['original_relative_path']).resolve()
            original.relative_to(data_root.resolve())
            if not original.is_file() or any(voice_library.replacement(sid,'sentence',original,voice) is None
                for voice in ('news-female','news-male')):
                return []
        return [{**row,'genre':'news'} for row in rows]
    except (ValueError, OSError, TypeError, KeyError):
        return []


def mixed_session(pool, *, count, filter_mode, seed=None, include_finals=None):
    eligible = apply_final_filter(pool,include_finals) if include_finals else apply_filter(pool,filter_mode)
    if not any(row.get('genre')=='news' for row in eligible):
        return build_session(pool,count=count,filter_mode=filter_mode,seed=seed,include_finals=include_finals)
    count = min(count,len(eligible))
    rng = random.Random(seed)
    news = [r for r in eligible if r.get('genre')=='news']
    literature = [r for r in eligible if r.get('genre')!='news']
    n_news = min(len(news),count//2+(rng.randrange(2) if count%2 else 0))
    n_literature = min(len(literature),count-n_news)
    n_news = min(len(news),count-n_literature)
    picked = []
    for bag,n in ((news,n_news),(literature,n_literature)):
        picked.extend(build_session(bag,count=n,filter_mode=filter_mode,seed=rng.randrange(2**32),include_finals=include_finals))
    rng.shuffle(picked)
    return picked
