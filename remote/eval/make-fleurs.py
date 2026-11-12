#!/usr/bin/env python3
"""
Make eval/fleurs-<config>.tsv for more languages from FLEURS's own index files, with the
same columns as fleurs-es_419.tsv. Run on a laptop, online:

    python3 -I eval/make-fleurs.py fr_fr pt_br sw_ke ar_eg ha_ng am_et

FLEURS is FLoRes sentences read aloud, so a sentence id is the same sentence in every
language. Every manifest gets the same 16 ids: the Spanish set's ids that all the given
languages recorded, then others they all have whose English is on the same themes
(health, water, food, disasters, children). Only dev and test clips (bootstrap.sh streams
a split's whole archive; train's are several GB), at most 30 s (Gemma's audio test reads
the first 30), one clip per id, female and male in turn where FLEURS has both (for
some languages its dev and test clips are read by one or two speakers). The English column is FLEURS's
en_us text for the id. The Spanish manifest stays as it is, so October's scores still
compare.
"""
import csv
import io
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
URL = 'https://huggingface.co/datasets/google/fleurs/resolve/main/data/{config}/{split}.tsv'
SPLITS = ('dev', 'test')
N, MAX_SECONDS, RATE = 16, 30.0, 16000
THEMES = {
    'health': ('health', 'disease', 'hospital', 'doctor', 'virus', 'infect', 'patient', 'medic'),
    'water': ('water', 'river', 'drink'),
    'food': ('food', 'crop', 'harvest', 'eat', 'farm'),
    'disaster': ('flood', 'storm', 'earthquake', 'hurricane', 'drought', 'tsunami'),
    'children': ('child', 'school', 'mother', 'family'),
}
LANG = {'fr_fr': 'fr', 'pt_br': 'pt', 'sw_ke': 'sw', 'ar_eg': 'ar', 'ha_ng': 'ha', 'am_et': 'am',
        'es_419': 'es', 'en_us': 'en'}


def rows(config):
    """[(split, id, file, transcript, seconds, gender)] from FLEURS's index for config."""
    out = []
    for split in SPLITS:
        with urllib.request.urlopen(URL.format(config=config, split=split), timeout=60) as r:
            text = r.read().decode('utf-8')
        for f in csv.reader(io.StringIO(text), delimiter='\t', quoting=csv.QUOTE_NONE):
            out.append((split, f[0], f[1], f[2], int(f[5]) / RATE, f[6].lower()))
    return out


def theme(english):
    low = english.lower()
    return next((t for t, words in THEMES.items() if any(re.search(rf'\b{w}', low) for w in words)), None)


def main(configs):
    by_config = {c: rows(c) for c in configs}
    english = {}
    for _, sid, _, text, _, _ in rows('en_us'):
        english.setdefault(sid, text)
    usable = [{sid for _, sid, _, _, secs, _ in by_config[c] if secs <= MAX_SECONDS} for c in configs]
    common = set.intersection(*usable) & set(english)

    spanish = [line.split('\t') for line in (HERE / 'fleurs-es_419.tsv').read_text(encoding='utf-8').splitlines()[1:]]
    ids = [(r[2], r[5]) for r in spanish if r[2] in common]
    for sid in sorted(common, key=int):
        if len(ids) >= N:
            break
        t = theme(english[sid])
        if t and sid not in {i for i, _ in ids}:
            ids.append((sid, t))
    if len(ids) < N:
        sys.exit(f'only {len(ids)} sentence ids common to {configs} on the themes')

    header = 'file\tsplit\tsentence_id\tgender\tseconds\ttopic\tlang\ttranscript\tenglish'
    for config in configs:
        lines, want = [header], 'female'
        for sid, topic in ids:
            clips = [r for r in by_config[config] if r[1] == sid and r[4] <= MAX_SECONDS]
            clip = next((r for r in clips if r[5] == want), clips[0])
            want = 'male' if clip[5] == 'female' else 'female'
            split, _, file, text, secs, gender = clip
            lines.append('\t'.join([file, split, sid, gender, f'{secs:.1f}', topic, LANG[config], text,
                                    english[sid]]))
        out = HERE / f'fleurs-{config}.tsv'
        out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        genders = sum(line.split('\t')[3] == 'female' for line in lines[1:])
        print(f'{out.name}: {len(lines) - 1} clips, {genders} female')


if __name__ == '__main__':
    main(sys.argv[1:] or ['fr_fr', 'pt_br', 'sw_ke', 'ar_eg', 'ha_ng', 'am_et'])
