"""Public, annotated continuous reading for nasal research; no app writes.

Attribution/research permission: https://lml-elearning.eduhk.hk/about_g.aspx
Audio URLs are recorded, not guessed. Unmarked characters are NOT positive labels.
"""
import argparse
import hashlib
import re
from pathlib import Path
import urllib.parse
import urllib.request

from lxml import html

from collect_eduhk_nasal import BASE, fetch_page, nasal_substitutions
from suntone_probe import private_json


def parse_passage(node):
    text, chars, annotations = [], [], []

    def add(value):
        text.append(value or '')
        chars.extend(c for c in (value or '') if '\u3400' <= c <= '\u9fff')

    def visit(element):
        if element.tag == 'font':
            if element.get('color', '').lower() != '#ff0000':
                return
            note = element.text_content().strip()
            errors = nasal_substitutions(note)
            if errors:
                if not chars or len(errors) != 1:
                    raise ValueError('Ambiguous passage annotation')
                annotations.append({'position': len(chars)-1, 'character': chars[-1], **errors[0]})
            return
        add(element.text)
        for child in element:
            visit(child)
            add(child.tail)

    visit(node)
    return {'text': ''.join(text).strip(), 'characters': ''.join(chars),
            'nasal_errors': annotations}


def main(args):
    folder = Path(args.directory)
    folder.mkdir(parents=True, exist_ok=True)
    browse = fetch_page(BASE + 'BrowseSpeakers_g.aspx', folder / 'browse.html')
    urls = sorted({urllib.parse.urljoin(BASE, href) for href in html.fromstring(browse).xpath('//a/@href')
                   if 'ViewTaskThree_g.aspx?id=' in href},
                  key=lambda url: int(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['id'][0]))
    rows = []
    for url in urls[:args.limit]:
        speaker = int(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['id'][0])
        raw = fetch_page(url, folder / f'speaker-{speaker}.html')
        annotated = folder / f'speaker-{speaker}-vowels.html'
        if not annotated.exists():
            doc = html.fromstring(raw)
            targets = doc.xpath('//a[contains(@href,"lnkbtnSelectAllVowel")]/@href')
            if len(targets) != 1:
                raise ValueError('Public vowel toggle missing')
            target = re.search(r"__doPostBack\('([^']+)'", targets[0]).group(1)
            fields = {e.get('name'): e.get('value', '') for e in doc.xpath('//input[@type="hidden"]')}
            fields.update(__EVENTTARGET=target, __EVENTARGUMENT='')
            request = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode())
            annotated.write_bytes(urllib.request.urlopen(request, timeout=30).read())
        doc = html.fromstring(annotated.read_bytes())
        paragraphs = doc.xpath('//span[contains(@id,"lblDisplayPara")]')
        sources = [urllib.parse.urljoin(BASE, s) for s in doc.xpath('//source/@src') if '/record/' in s]
        if len(paragraphs) != 2 or len(sources) != 2:
            raise ValueError('Unexpected paragraph/audio layout')
        for index, (node, source) in enumerate(zip(paragraphs, sources), start=1):
            rows.append({'speaker': speaker, 'passage': index, 'source': url, 'audio_url': source,
                         'annotation_page_sha256': hashlib.sha256(annotated.read_bytes()).hexdigest(),
                         **parse_passage(node)})
        private_json(folder / 'annotations.json', {'complete': False, 'rows': rows})
        print('speaker', speaker, 'nasal_errors', sum(len(r['nasal_errors']) for r in rows[-2:]), flush=True)
    private_json(folder / 'annotations.json', {'complete': True, 'source': BASE + 'about_g.aspx',
                                             'scope': 'Annotated errors only; no unmarked-positive assumption', 'rows': rows})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', default='data/derived/nasal-acoustic-validation/eduhk-passages')
    parser.add_argument('--limit', type=int, default=40)
    main(parser.parse_args())
