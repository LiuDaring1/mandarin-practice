"""Cache public EdUHK feature annotations for local research evaluation.

Research permission and attribution: https://lml-elearning.eduhk.hk/about_g.aspx
Do not redistribute recordings or use them as the app's teaching material.
Only follows public browse links and their read-only 'select all vowel' form.
"""
import argparse
import json
from pathlib import Path
import re
import unicodedata
import urllib.parse
import urllib.request

from lxml import html

BASE = "https://lml-elearning.eduhk.hk/"


def plain_pinyin(value):
    value = value.replace("ü", "v").replace("ǖ", "v").replace("ǘ", "v").replace("ǚ", "v").replace("ǜ", "v")
    return "".join(c for c in unicodedata.normalize("NFD", value) if not unicodedata.combining(c)).lower().strip()


def nasal_substitutions(annotation):
    errors = []
    for expected, actual in re.findall(r"([^\s→]+)→([^\s→]+)", annotation):
        left, right = plain_pinyin(expected), plain_pinyin(actual)
        if (left.endswith("n") and right == left + "g") or (left.endswith("ng") and right == left[:-1]):
            errors.append({"expected_pinyin": expected, "actual_pinyin": actual,
                           "expected_plain": left, "actual_plain": right,
                           "actual_group": "back" if right.endswith("ng") else "front"})
    return errors


def parse_annotations(raw, speaker, source):
    doc = html.fromstring(raw)
    rows = []
    for node in doc.xpath('//span[contains(@id,"ResultElement")]'):
        task = 1 if "TaskOne" in node.get("id", "") else 2
        position = int(re.search(r"_ctl(\d+)_", node.get("id")).group(1))
        word = "".join(node.xpath('./text()[not(preceding-sibling::br)] | ./b[not(preceding-sibling::br)]//text()')).strip()
        annotations = [f.text_content().strip() for f in node.xpath('.//font')]
        errors = []
        for annotation in annotations:
            errors.extend(nasal_substitutions(annotation))
        rows.append({"speaker": speaker, "task": task, "word_index": position, "word": word,
                     "vowel_annotations": annotations, "nasal_errors": errors, "source": source})
    return rows


def fetch_page(url, destination):
    if not destination.exists():
        destination.write_bytes(urllib.request.urlopen(url, timeout=30).read())
    return destination.read_bytes()


def main(args):
    folder = Path(args.directory)
    folder.mkdir(parents=True, exist_ok=True)
    browse = fetch_page(BASE + "BrowseSpeakers_g.aspx", folder / "browse.html")
    urls = []
    for href in html.fromstring(browse).xpath('//a/@href'):
        if "ViewTaskOneAndTwo_g.aspx?id=" in href:
            url = urllib.parse.urljoin(BASE, href)
            if url not in urls:
                urls.append(url)
    rows = []
    for url in urls[:args.limit]:
        speaker = int(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["id"][0])
        raw = fetch_page(url, folder / f"speaker-{speaker}.html")
        annotated = folder / f"speaker-{speaker}-vowels.html"
        if not annotated.exists():
            doc = html.fromstring(raw)
            targets = doc.xpath('//a[contains(@href,"lnkbtnSelectAllVowel")]/@href')
            if len(targets) != 1:
                raise ValueError("Public annotation toggle missing")
            target = re.search(r"__doPostBack\('([^']+)'", targets[0]).group(1)
            fields = {e.get("name"): e.get("value", "") for e in doc.xpath('//input[@type="hidden"]')}
            fields.update(__EVENTTARGET=target, __EVENTARGUMENT="")
            request = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode())
            annotated.write_bytes(urllib.request.urlopen(request, timeout=30).read())
        sample = parse_annotations(annotated.read_bytes(), speaker, url)
        if not sample:
            raise ValueError("No word annotations parsed")
        rows.extend(sample)
        print("speaker", speaker, "words", len(sample), "nasal error targets", sum(len(r["nasal_errors"]) for r in sample), flush=True)
        output = folder / "annotations.json"
        output.write_text(json.dumps({"source": BASE + "about_g.aspx", "purpose": "local research evaluation only",
                                      "rows": rows}, ensure_ascii=False, indent=2))
        output.chmod(0o600)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", default="data/derived/nasal-acoustic-validation/eduhk")
    parser.add_argument("--limit", type=int, default=40)
    main(parser.parse_args())
