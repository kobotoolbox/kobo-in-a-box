#!/usr/bin/env python3
"""
Build or refresh the knowledge index from the library's pages (knowledge.sh index).

    python -I index.py [--collection <id>...] [--full]

Each collection in collections.json is a set of folders under the library (/library, the
box's /srv/library). A page whose text is unchanged since the last run (same model) is
skipped; pages gone from the library leave the index. --full re-embeds everything (a new
embedding model needs it, and index.py does it by itself when the model changed).
"""
import argparse
import fnmatch
import json
import os
import sys
import time
from pathlib import Path

import kb

HERE = Path(__file__).resolve().parent
LIBRARY = Path(os.environ.get('LIBRARY', '/library'))
LIBRARY_URL = os.environ.get('LIBRARY_URL', 'http://kobo.local').rstrip('/')
SKIP = ['genindex.html', 'search.html', '404.html', 'py-modindex.html', '_*', '*/_*']


def pages(col):
    """(path, url, article) of each page of a collection. The article is the page's
    path with its language folder taken out, so a page's translations share one."""
    for d in col['dirs']:
        root = LIBRARY / d
        for f in sorted(root.rglob('*.html')):
            rel = f.relative_to(root).as_posix()
            if any(fnmatch.fnmatch(rel, p) for p in SKIP + col.get('exclude', [])):
                continue
            yield f, f'{LIBRARY_URL}/{d}/{rel}', rel


def article_key(rel, lang):
    parts = rel.split('/')
    return '/'.join(parts[1:]) if len(parts) > 1 and parts[0] == lang else rel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--collection', action='append')
    ap.add_argument('--full', action='store_true')
    args = ap.parse_args()
    cols = [c for c in json.load(open(HERE / 'collections.json')) if c.get('enabled', True)]
    if args.collection:
        cols = [c for c in cols if c['id'] in args.collection]
    db = kb.connect()
    model = kb.embed_model()
    old = dict(db.execute('SELECT key, value FROM meta')).get('embed_model')
    if old and old != model:
        print(f'embedding model changed ({old} -> {model}): re-embedding everything')
        args.full = True
    t0, embedded, kept = time.time(), 0, 0
    for col in cols:
        db.execute('INSERT OR REPLACE INTO collections VALUES (?,?,?,?,?)',
                   (col['id'], col['title'], col['boost'], col['source'], col['licence']))
        seen = set()
        known = dict(db.execute('SELECT url, sha1 FROM pages WHERE collection = ?', (col['id'],)))
        for f, url, rel in pages(col):
            lang, text = kb.page_text(f.read_text(encoding='utf-8', errors='replace'))
            if len(text) < 100:
                continue
            seen.add(url)
            digest = kb.sha1(text)
            if not args.full and known.get(url) == digest:
                kept += 1
                continue
            title, chunks = kb.chunk_page(text)
            if not chunks:
                continue
            vecs = kb.embed([c['text'] for c in chunks])
            kb.put_page(db, col['id'], url, lang or col.get('lang', 'en'), article_key(rel, lang),
                        title, digest, chunks, vecs)
            embedded += 1
            if embedded % 50 == 0:
                db.commit()
                print(f'  {col["id"]}: {embedded} pages embedded ({time.time() - t0:.0f} s)', flush=True)
        for url in set(known) - seen:
            kb.drop_page(db, url)
        db.commit()
    for k, v in (('embed_model', model), ('built', time.strftime('%Y-%m-%dT%H:%M:%S%z'))):
        db.execute('INSERT OR REPLACE INTO meta VALUES (?, ?)', (k, v))
    db.commit()
    n_pages, n_chunks = db.execute('SELECT (SELECT COUNT(*) FROM pages), (SELECT COUNT(*) FROM chunks)').fetchone()
    db.execute('VACUUM')
    print(f'index: {n_pages} pages, {n_chunks} chunks; {embedded} pages embedded, {kept} unchanged, '
          f'{time.time() - t0:.0f} s, model {model}')


if __name__ == '__main__':
    sys.exit(main())
