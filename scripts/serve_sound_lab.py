#!/usr/bin/env python3
"""Read-only, allowlisted sound preview. Does not import the application or its progress code."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote
import argparse, json, mimetypes, re

ROOT=Path(__file__).resolve().parents[1]
LAB=ROOT/'assets/sound-design'
DEMO=ROOT/'data/derived/clips-v2/table1/t1-00019.wav'
INSTALLED=ROOT/'src/pth_corpus/prototype_static/sounds'
R4ORCE_FILES={s['url'].lstrip('/') for s in json.loads((LAB/'library-manifest.json').read_text()).get('extra_samples',[])} | {'external/r4orce/License.txt','external/r4orce/Readme.txt'}
class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self): self.serve(False)
    def do_GET(self): self.serve(True)
    def serve(self,body):
        route=unquote(urlsplit(self.path).path)
        if route=='/__qa/info':
            data=json.dumps({'isolated':True,'read_only':True,'progress_dir':None,'kind':'sound-lab','teaching_word':'安心','teaching_item':'t1-00019'}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers()
            if body:self.wfile.write(data)
            return
        if route=='/teaching.wav': p=DEMO
        elif route.startswith('/installed-sounds/'):
            name=route.removeprefix('/installed-sounds/')
            allowed={'manifest.json'} | {f for s in json.loads((INSTALLED/'manifest.json').read_text())['sounds'] for f in s['variants']}
            if name not in allowed:return self.send_error(404)
            p=INSTALLED/name
        elif route.startswith('/illustrations/'):
            name=route.removeprefix('/illustrations/')
            if name not in ['listen.webp','welcome.webp','beading.webp','celebrate.webp','orange.webp','violet.webp']:
                return self.send_error(404)
            p=ROOT/'src/pth_corpus/prototype_static/illustrations'/name
        else:
            rel=route.lstrip('/') or 'installed.html'
            if rel in ['index.html','lab.css','lab.js','sound-manager.js','manifest.json','README.md',
                       'library.html','library.css','library.js','library-manifest.json','LIBRARIES.md','installed.html']:
                p=LAB/rel
            elif re.fullmatch(r'external/dustyroom/(?:DM-CGS-(?:0[1-9]|[1-4][0-9]|50)\.wav|LICENSE\.txt|license\.pdf)', rel):
                p=LAB/rel
            elif rel in R4ORCE_FILES:
                p=LAB/rel
            elif rel.startswith('exports/') and '/' not in rel[8:] and rel.endswith('.wav'):
                p=LAB/rel
            else:return self.send_error(404)
        if not p.is_file():return self.send_error(404)
        data=p.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type',mimetypes.guess_type(str(p))[0] or 'application/octet-stream')
        self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
        if body:
            try:self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError):pass
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8772);args=parser.parse_args()
    print(f'Independent sound lab: http://127.0.0.1:{args.port}/ (no progress writes)',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
