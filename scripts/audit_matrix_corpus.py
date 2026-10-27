"""Read-only inventory of the official CMNmatrix archive; no diagnosis labels.

The published word table suggests a numeric filename mapping. This script keeps
that mapping explicitly provisional and never treats an ASR transcript as a
human actual-phone annotation. Missing paired recordings remain in the audit.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

from nasal_validation_execution import durable_json

SENTENCE = re.compile(r'(S[FM][0-9]{2}_CMN)/(Lombard|Plain)/([0-9]{5})\.wav')
STYLES = ('Lombard', 'Plain')


def inventory(names):
    if len(names) != len(set(names)):
        raise ValueError('Duplicate archive path')
    groups = defaultdict(set)
    auxiliary = []
    directories = []
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name or str(path) != name:
            raise ValueError('Unsafe or noncanonical archive path')
        match = SENTENCE.fullmatch(name)
        if match:
            speaker, style, code = match.groups()
            groups[speaker, style].add(code)
        elif name == 'icra1.wav' or re.fullmatch(
                r'S[FM][0-9]{2}_CMN/(Lombard|Plain)/finalnoise(?:_short_[FM][0-9]{2}_(?:Lombard|Plain))?\.wav', name):
            auxiliary.append(name)
        elif re.fullmatch(r'S[FM][0-9]{2}_CMN(?:/(?:Lombard|Plain))?', name):
            directories.append(name)
        else:
            raise ValueError('Unclassified archive entry: ' + name)
    speakers = sorted({speaker for speaker, _ in groups})
    codes = sorted(set().union(*groups.values())) if groups else []
    if not speakers or not codes:
        raise ValueError('No sentence recordings')
    missing = [f'{speaker}/{style}/{code}.wav'
               for speaker in speakers for style in STYLES for code in codes
               if code not in groups.get((speaker, style), set())]
    expected = len(speakers) * len(STYLES) * len(codes)
    return {'speakers': speakers, 'styles': list(STYLES), 'sentence_codes': codes,
            'expected_sentence_recordings': expected,
            'available_sentence_recordings': sum(map(len, groups.values())),
            'missing_recordings': missing, 'auxiliary_audio': auxiliary,
            'directories': directories,
            'by_group': {f'{speaker}/{style}': len(groups.get((speaker, style), set()))
                         for speaker in speakers for style in STYLES},
            'speaker_prefix_counts': dict(Counter(speaker[1] for speaker in speakers)),
            'human_actual_phone_annotations_imported': False,
            'filename_to_text_verified': False, 'diagnostic_accuracy_measured': False}


def candidate_text(code, table):
    if not re.fullmatch('[0-9]{5}', code):
        raise ValueError('Expected a five-digit sentence code')
    if (len(table) != 10 or any(len(row) != 5 for row in table) or
            any(not isinstance(word, str) or not word for row in table for word in row)):
        raise ValueError('Expected the published 10 by 5 word matrix')
    return ''.join(table[int(digit)][column] for column, digit in enumerate(code))


def checksum(path):
    md5, sha256 = hashlib.md5(), hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            md5.update(block)
            sha256.update(block)
    return {'md5': md5.hexdigest(), 'sha256': sha256.hexdigest()}


def main(args):
    out = Path(args.out)
    if out.exists():
        raise ValueError('Inventory already exists; do not overwrite')
    record = json.loads(Path(args.record).read_text())
    source = next(f for f in record['files'] if f['key'] == 'wavfiles.rar')
    archive = Path(args.archive)
    digests = checksum(archive)
    if archive.stat().st_size != source['size'] or 'md5:' + digests['md5'] != source['checksum']:
        raise ValueError('Official archive checksum or size mismatch')
    listing = subprocess.run([args.bsdtar, '-tf', str(archive)],
                             check=True, capture_output=True, text=True).stdout
    result = inventory(listing.splitlines())
    if len(result['speakers']) != 11 or len(result['sentence_codes']) != 100:
        raise ValueError('Archive does not match the documented speaker/code inventory')
    table = json.loads(Path(args.table).read_text())
    # Four anchors selected by metadata only, before recognition or scoring.
    speaker = result['speakers'][0]
    anchors = [{'member': f'{speaker}/{style}/{code}.wav',
                'candidate_reference': candidate_text(code, table['rows'])}
               for code in result['sentence_codes'][:2] for style in STYLES]
    if any(anchor['member'] in result['missing_recordings'] for anchor in anchors):
        raise ValueError('A prespecified identity anchor is missing; do not replace it')
    durable_json(out, {**result, 'archive': str(archive.resolve()), 'archive_digests': digests,
        'source_record_sha256': hashlib.sha256(Path(args.record).read_bytes()).hexdigest(),
        'word_table_sha256': hashlib.sha256(Path(args.table).read_bytes()).hexdigest(),
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'identity_check_anchors': anchors,
        'label_scope': 'Published whole-recording pronunciation QC, not per-phone human labels.',
        'asr_scope': 'Optional content-identity check only; never actual-phone ground truth.',
        'new_api_requests': 0, 'production_enabled': False})
    print(json.dumps({k: result[k] for k in ('expected_sentence_recordings',
          'available_sentence_recordings', 'speaker_prefix_counts')}, ensure_ascii=False))
    print('MISSING', len(result['missing_recordings']), 'AUXILIARY', len(result['auxiliary_audio']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for option in ('archive', 'record', 'table', 'out'):
        parser.add_argument('--' + option, required=True)
    parser.add_argument('--bsdtar', default='bsdtar')
    main(parser.parse_args())
