#!/usr/bin/env python3
"""
Retrieval checks for the knowledge base (knowledge.sh eval), on the index as built.

    python -I eval.py [--out <report.json>] [--k 8]

Cases: cases/box.yaml, and the support bot's in cases/support-bot/ when they're there
(kobo-support-bot-poc backend/evals/cases, a private repo: `knowledge.sh cases <checkout>`
copies them in, and git ignores them). A case with expect.retrieve_any passes at k
when one of those pages is among the first k results; support.kobotoolbox.org/<slug>
stands for the same article on the box in any language. For each search mode (vector,
fts, hybrid): hit@1/3/5/k, MRR, and for questions in a language the guide has, whether
the first result is in that language. Cases with nothing to retrieve (unanswerable,
hallucination bait) give the best similarity a question with no answer gets, next to
the answerable ones', to set a "not covered" line by.
"""
import argparse
import glob
import json
import os
import re
import statistics
import time

import yaml

import kb

HERE = os.path.dirname(os.path.abspath(__file__))
MODES = ('vector', 'fts', 'hybrid')


def article_of(url):
    """support.kobotoolbox.org/<slug>[.html] -> the guide's article key (<slug>.html)."""
    m = re.match(r'https?://support\.kobotoolbox\.org/(?:(?:es|fr|ar)/)?([^/#?]+?)(?:\.html)?/?$', url)
    return ('kobo-guide', f'{m.group(1)}.html') if m else (None, url)


def load_cases():
    cases = []
    for f in sorted(glob.glob(os.path.join(HERE, 'cases', '**', '*.yaml'), recursive=True)):
        for c in yaml.safe_load(open(f)) or []:
            c['file'] = os.path.basename(f)
            cases.append(c)
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out')
    ap.add_argument('--k', type=int, default=8)
    args = ap.parse_args()
    index = kb.Index()
    langs = {r[7] for r in index.rows.values()}
    cases = load_cases()
    t = time.time()
    qvecs = kb.embed([c['message'] for c in cases])
    embed_ms = (time.time() - t) * 1000 / max(len(cases), 1)
    results, rows = {m: [] for m in MODES}, []
    for c, qv in zip(cases, qvecs):
        want = {article_of(u) for u in (c.get('expect') or {}).get('retrieve_any') or []}
        row = {'id': c['id'], 'file': c['file'], 'language': c.get('language', 'en'), 'answerable': bool(want)}
        for mode in MODES:
            hits = index.search(c['message'], k=args.k, mode=mode, qvec=qv)
            rank = next((i + 1 for i, h in enumerate(hits) if (h['collection'], h['article']) in want), None)
            top = hits[0] if hits else None
            row[mode] = {'rank': rank, 'top': top and top['url'], 'top_lang': top and top['lang'],
                         'top_similarity': top and top['similarity'] if mode != 'fts' else None}
            if want:
                results[mode].append((rank, row['language'], top and top['lang']))
        # The best a question gets by meaning alone, answerable or not
        row['best_similarity'] = float((index.vecs @ qv).max()) if len(index.ids) else None
        rows.append(row)

    def summary(rs):
        n = len(rs)
        out = {f'hit@{k}': round(sum(1 for r, _, _ in rs if r and r <= k) / n, 3) for k in (1, 3, 5, args.k)}
        out['mrr'] = round(sum(1 / r for r, _, _ in rs if r) / n, 3)
        own = [(l, tl) for _, l, tl in rs if l in langs and l != 'en']
        out['same_language@1'] = round(sum(1 for l, tl in own if l == tl) / len(own), 3) if own else None
        out['cases'] = n
        return out

    report = {
        'built': index.meta.get('built'), 'embed_model': index.meta.get('embed_model'),
        'chunks': len(index.ids), 'pages': len(index.pages), 'k': args.k,
        'embed_ms_per_query': round(embed_ms),
        'modes': {m: summary(results[m]) for m in MODES},
        'by_file': {f: {m: summary([x for x, r in zip(results[m], [r for r in rows if r['answerable']])
                                    if r['file'] == f]) for m in MODES}
                    for f in sorted({r['file'] for r in rows if r['answerable']})},
        'similarity': {
            'answerable': sorted(round(r['best_similarity'], 3) for r in rows if r['answerable']),
            'unanswerable': sorted(round(r['best_similarity'], 3) for r in rows if not r['answerable']),
        },
        'cases': rows,
    }
    sa, su = report['similarity']['answerable'], report['similarity']['unanswerable']
    print(f"index: {report['pages']} pages, {report['chunks']} chunks, {report['embed_model']}; "
          f"{len(sa)} answerable cases, {len(su)} with no answer; {report['embed_ms_per_query']} ms/query to embed")
    print(f"{'mode':8} " + ' '.join(f'{k:>8}' for k in report['modes']['hybrid'] if k != 'cases'))
    for m in MODES:
        print(f'{m:8} ' + ' '.join(f'{"-" if v is None else v:>8}' for k, v in report['modes'][m].items() if k != 'cases'))
    print('misses (hybrid, not in the first k): ' + ', '.join(
        r['id'] for r in rows if r['answerable'] and not r['hybrid']['rank']) or 'none')
    if sa and su:
        print(f'best similarity: answerable median {statistics.median(sa):.3f} (min {sa[0]:.3f}), '
              f'no answer median {statistics.median(su):.3f} (max {su[-1]:.3f})')
    if args.out:
        json.dump(report, open(args.out, 'w'), indent=2, ensure_ascii=False)
        print(f'report: {args.out}')


if __name__ == '__main__':
    main()
