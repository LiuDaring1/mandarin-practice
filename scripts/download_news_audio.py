"""Download only public media URLs discovered from news pages in Ego Lite."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / 'data/raw/news-wechat-v1'
    failures = {}
    def download(row):
        path = root / row['file']
        if path.is_file() and path.stat().st_size > 1000:
            return True
        if failures.get(row['file'], 0) >= 3:
            return False
        url = urlsplit(row['url'])
        if url.scheme != 'https' or url.hostname != 'res.wx.qq.com' or url.path != '/voice/getvoice':
            raise ValueError('unexpected media origin')
        try:
            with httpx.Client(timeout=20,follow_redirects=True) as client:
                response = client.get(row['url']); response.raise_for_status()
            if len(response.content) < 1000 or response.content.lstrip().startswith((b'<',b'{')):
                raise ValueError('not an audio response')
            temporary = path.with_suffix('.part')
            temporary.write_bytes(response.content); temporary.replace(path)
            return True
        except Exception:
            failures[row['file']] = failures.get(row['file'],0)+1
            return False
    with ThreadPoolExecutor(max_workers=6) as pool:
        for iteration in range(360):
            rows = []
            for file in root.glob('*.json'):
                try:
                    data=json.loads(file.read_text());rows.extend(data.get('audio_files',[]) if isinstance(data,dict) else [])
                except (ValueError,OSError):pass
            successes = sum(pool.map(download,rows))
            if iteration%4 == 0:print(json.dumps({'downloaded':successes,'discovered':len(rows)}),flush=True)
            if not args.watch or (root/'collection-complete.json').is_file():break
            time.sleep(5)
    print(json.dumps({'complete':True,'downloaded':successes,'discovered':len(rows),'failures':failures}),flush=True)


if __name__ == '__main__':main()
