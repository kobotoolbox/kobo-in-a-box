#!/usr/bin/env python3
"""
One table of benchmark runs (MODELS-PLAN.md section 4): every smoke-test.py result with a
recipe name (gpu-tiers.sh) in the given folders, the newest run of each recipe per machine.
Writes CSV (for site/charts.py) and prints Markdown:

    python3 -I eval/bench-table.py results/ [more folders] [--csv out.csv] [--langs]

--langs adds a column per language: transcription WER and translation chrF (into English /
from English), and extended-set qual correct/total.
"""
import argparse
import csv
import json
import sys
from pathlib import Path


def ratio(rows):
    rows = list(rows)
    return f"{sum(r.get('status') == 'CORRECT' for r in rows)}/{len(rows)}" if rows else ''


def med(values):
    v = sorted(x for x in values if x is not None)
    return round(v[len(v) // 2], 2) if v else None


def machine(r):
    gpu = (r.get('gpu_after') or {}).get('gpu')
    return gpu or 'CPU'


def row(r, langs):
    s = r.get('scores') or {}
    calls = r.get('qual', []) + r.get('typed_qual', []) + r.get('photo_qual', [])
    ext = r.get('qual_extended', []) + r.get('photo_extended', [])
    # the first question on each photo is without the prompt cache: counted apart
    photo_first = [x for x in r.get('photo_extended', []) + r.get('photo_qual', []) if not x.get('cached', True)]
    out = {
        'recipe': r.get('recipe'), 'model': r.get('llm_model'), 'machine': machine(r),
        'egress': r.get('egress'),
        'whisper_wer': s.get('whisper_wer'), 'gemma_audio_wer': s.get('gemma_audio_wer'),
        'mt_chrf': s.get('mt_chrf'), 'pipeline_chrf': s.get('pipeline_chrf'),
        'qual_october': ratio(calls), 'qual_extended': ratio(r.get('qual_extended', [])),
        'photos_extended': ratio(r.get('photo_extended', [])), 'extended_all': ratio(ext),
        'secs_per_question': med(x.get('secs') for x in calls + ext if x.get('cached', True)),
        'secs_first_photo_question': med(x.get('secs') for x in photo_first),
        'gen_tokens_per_s': med(((x.get('timings') or {}).get('predicted_per_second')) for x in calls + ext),
        'vram_mb': (r.get('gpu_after') or {}).get('vram_used_mb'),
        'gpu_avg_w': (r.get('gpu_power') or {}).get('avg_w'),
        'started': r.get('started'),
    }
    if langs:
        for lang, sc in (r.get('scores_by_lang') or {}).items():
            out[f'{lang}_wer'] = sc.get('whisper_wer')
            out[f'{lang}_chrf_to_en'] = sc.get('mt_chrf')
            out[f'{lang}_chrf_from_en'] = sc.get('from_en_chrf')
            out[f'{lang}_gemma_audio_wer'] = sc.get('gemma_audio_wer')
        for lang in sorted({x['lang'] for x in r.get('qual_extended', [])}):
            out[f'{lang}_qual'] = ratio(x for x in r['qual_extended'] if x['lang'] == lang)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('folders', nargs='+')
    ap.add_argument('--csv')
    ap.add_argument('--langs', action='store_true')
    args = ap.parse_args()
    newest = {}
    for folder in args.folders:
        for f in sorted(Path(folder).glob('*.json')):
            try:
                r = json.loads(f.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(r, dict) or not r.get('recipe'):
                continue
            key = (r['recipe'], machine(r))
            if key not in newest or r.get('started', '') > newest[key].get('started', ''):
                newest[key] = r
    rows = [row(r, args.langs) for _, r in sorted(newest.items())]
    if not rows:
        sys.exit('no results with a recipe name (gpu-tiers.sh writes them)')
    cols = list(dict.fromkeys(k for r in rows for k in r))
    if args.csv:
        with open(args.csv, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, cols)
            w.writeheader()
            w.writerows(rows)
    print('| ' + ' | '.join(cols) + ' |')
    print('|' + '---|' * len(cols))
    for r in rows:
        print('| ' + ' | '.join('' if r.get(c) is None else str(r.get(c)) for c in cols) + ' |')


if __name__ == '__main__':
    main()
