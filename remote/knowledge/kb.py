"""
The box's knowledge base (W10, PLAN 3i): pages from the offline library, cut into
sections, embedded, and searched by meaning and by exact words together.

Used by index.py (building the index), server.py (the agent's tools) and eval.py.

- Pages are the library's own HTML (http://kobo.local/docs/...), so a citation opens
  offline. The text comes from the page's main element (role="main"), as Markdown-like
  text with its headings.
- Chunking is the support bot's (kobo-support-bot-poc indexer.py): split at H2-H4, merge
  small sections up to ~1,600 characters, split above ~2,400 at paragraphs, and start each
  chunk with "[Article: ...] [Section: ...]". Here a chunk also keeps the section's anchor.
- The store is one SQLite file: chunks, an FTS5 table over them, and the embeddings
  (float16, normalised). A few thousand chunks, so a search reads them all.
- Search: the vector ranking and the FTS ranking fused by reciprocal rank, times the
  collection's boost; one language per article (the asker's, usually, as it ranks first).
"""
import hashlib
import json
import os
import re
import sqlite3
import urllib.request
from html.parser import HTMLParser

import numpy as np

EMBED_URL = os.environ.get('EMBED_URL', 'http://embed:8080')
DB_PATH = os.environ.get('KNOWLEDGE_DB', '/data/knowledge.db')

MAX_CHUNK_CHARS = 600 * 4   # the bot's sizes (1 token ~ 4 characters)
TARGET_CHUNK_CHARS = 400 * 4
RRF_K = 60                  # reciprocal rank fusion's usual constant
CANDIDATES = 50             # from each ranking, before fusing
PER_ARTICLE = 2             # sections from one page at most, so others get a place
FTS_WEIGHT = float(os.environ.get('FTS_WEIGHT', '0.5'))  # the word ranking's share in the fusion
OTHER_LANGUAGE = 0.8        # weight of a page in another language than the question's

# Common words of the guide's languages, to tell which one a question is in (the rest: any
# other language, which gets English pages first: the guide's own)
_COMMON = {
    'en': 'the a an to of and is in how do i my can what does it for on with be are this you not when why',
    'es': 'el la los las de que y en un una cómo como mi puedo qué por para con no se es del al lo me',
    'fr': 'le la les de des du et en un une comment je mon ma mes est pour que qui dans pas avec sur ne au',
}
_COMMON = {lang: set(words.split()) for lang, words in _COMMON.items()}


# --- Pages to text --------------------------------------------------------------------

class _PageText(HTMLParser):
    """The main element's text as Markdown-ish lines: '#' headings with the id of their
    section (for #anchors), '- ' list items, code kept. Skips scripts, iframes, the
    heading permalinks ('¶') and anything outside role="main"."""
    SKIP = {'script', 'style', 'iframe', 'nav', 'footer', 'form', 'button', 'svg'}
    BLOCK = {'p', 'div', 'section', 'li', 'tr', 'pre', 'dt', 'dd', 'table', 'ul', 'ol',
             'blockquote', 'figcaption', 'br'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lang = ''
        self.depth = 0        # open elements inside main (0: not in main)
        self.skip = 0         # open elements inside something skipped
        self.out = []
        self.heading = None   # level of the heading being read
        self.anchor = ''      # id of the innermost open section
        self.sections = []    # stack of (depth, id)
        self.cell = 0         # open table cells: their paragraphs stay on the row's line
        self.table = 0        # open tables

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'html':
            self.lang = (a.get('lang') or '').split('-')[0].lower()
        if self.depth == 0:
            if a.get('role') == 'main':
                self.depth = 1
            return
        self.depth += 1
        if self.skip or tag in self.SKIP or 'headerlink' in (a.get('class') or ''):
            self.skip += 1
            return
        if a.get('id') and tag in ('section', 'div'):
            self.sections.append((self.depth, a['id']))
        if re.fullmatch(r'h[1-6]', tag):
            self.heading = int(tag[1])
            anchor = self.sections[-1][1] if self.sections else ''
            self.out.append(f'\n\n{"#" * self.heading} \x00{anchor}\x00')
        elif tag == 'li':
            self.out.append('\n- ')
        elif tag in ('td', 'th'):
            self.cell += 1
            self.out.append(' | ')
        elif tag == 'tr':
            self.out.append('\n')
        elif tag == 'table':
            self.table += 1
            self.out.append('\n')
        elif self.cell and tag in self.BLOCK:
            self.out.append(' ')
        elif tag == 'pre':
            self.out.append('\n```\n')
        elif tag in self.BLOCK:
            self.out.append('\n\n' if tag == 'p' else '\n')

    def handle_endtag(self, tag):
        if self.depth == 0:
            return
        if self.skip:
            self.skip -= 1
        elif re.fullmatch(r'h[1-6]', tag):
            self.heading = None
            self.out.append('\n')
        elif tag == 'pre':
            self.out.append('\n```\n')
        elif tag in ('td', 'th'):
            self.cell -= 1
        elif tag == 'table':
            self.table -= 1
        while self.sections and self.sections[-1][0] >= self.depth:
            self.sections.pop()
        self.depth -= 1

    def handle_data(self, data):
        if self.depth and not self.skip:
            if self.cell or self.heading is not None:
                data = data.replace('\n', ' ')
            elif data.isspace() and self.table:
                return   # the markup's own line breaks between cells and rows
            self.out.append(data)


def page_text(raw_html):
    """(language, text) of a library page; headings carry their anchor as '\\0id\\0'."""
    p = _PageText()
    p.feed(raw_html)
    text = ''.join(p.out)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return p.lang, text.strip()


# --- Chunking (the support bot's, with anchors) -----------------------------------------

_HEADING = re.compile(r'^(#{1,4})\s+\x00([^\x00]*)\x00(.*)$', re.MULTILINE)


def _prefix_len(title, heading):
    return len(f'[Article: {title}]' + (f' [Section: {heading}]' if heading else '')) + 1


def _split_long(sec, title):
    budget = MAX_CHUNK_CHARS - _prefix_len(title, sec['heading'])
    parts = []
    for para in [p.strip() for p in re.split(r'\n{2,}', sec['body']) if p.strip()]:
        # A "paragraph" still too long (a flat list): its lines instead
        parts.extend([l.strip() for l in para.split('\n') if l.strip()] if len(para) > budget else [para])
    chunks, cur, n = [], [], 0
    for part in parts:
        if n + len(part) > budget and cur:
            chunks.append({**sec, 'body': '\n'.join(cur)})
            cur, n = [], 0
        cur.append(part[:budget])
        n += len(part)
    if cur:
        chunks.append({**sec, 'body': '\n'.join(cur)})
    return chunks


def _merge_small(sections, title):
    if not sections:
        return sections
    merged = [dict(sections[0])]
    for sec in sections[1:]:
        prev = merged[-1]
        size = _prefix_len(title, prev['heading']) + len(prev['body']) + len(sec['heading']) + len(sec['body']) + 4
        if size <= TARGET_CHUNK_CHARS:
            prev['body'] += f"\n\n**{sec['heading']}**\n{sec['body']}" if sec['heading'] else f"\n\n{sec['body']}"
        else:
            merged.append(dict(sec))
    return merged


def chunk_page(text):
    """(title, chunks) of a page's text; each chunk {heading, anchor, body, text}."""
    matches = list(_HEADING.finditer(text))
    title = next((m.group(3).strip() for m in matches if len(m.group(1)) == 1), '') \
        or (matches[0].group(3).strip() if matches else 'Untitled')
    sections = []
    pre = text[:matches[0].start()].strip() if matches else text.strip()
    if pre:
        sections.append({'heading': '', 'anchor': '', 'body': pre})
    for i, m in enumerate(matches):
        body = text[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)].strip()
        if not body:
            continue
        if len(m.group(1)) == 1:   # the page's own title: its intro, under no section
            sections.append({'heading': '', 'anchor': '', 'body': body})
        else:
            sections.append({'heading': m.group(3).strip(), 'anchor': m.group(2), 'body': body})
    out = []
    for sec in _merge_small(sections, title):
        if len(sec['body']) + _prefix_len(title, sec['heading']) > MAX_CHUNK_CHARS:
            out.extend(_split_long(sec, title))
        else:
            out.append(sec)
    for c in out:
        prefix = f'[Article: {title}]' + (f" [Section: {c['heading']}]" if c['heading'] else '')
        c['text'] = prefix + '\n' + c['body']
        c['anchor'] = c['anchor'] if c['heading'] else ''
    return title, out


# --- Embeddings ---------------------------------------------------------------------------

def embed(texts, batch=32):
    """Normalised float32 vectors from the embedding server (llama-server, OpenAI API)."""
    out = []
    for i in range(0, len(texts), batch):
        body = json.dumps({'input': texts[i:i + batch]}).encode()
        req = urllib.request.Request(f'{EMBED_URL}/v1/embeddings', data=body,
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=600) as r:
            data = sorted(json.load(r)['data'], key=lambda d: d['index'])
        out.extend(d['embedding'] for d in data)
    v = np.asarray(out, dtype=np.float32)
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)


def embed_model():
    """The embedding server's model file name, recorded with the index."""
    try:
        with urllib.request.urlopen(f'{EMBED_URL}/v1/models', timeout=10) as r:
            return json.load(r)['data'][0]['id']
    except (OSError, ValueError, KeyError, IndexError):
        return 'unknown'


# --- The store --------------------------------------------------------------------------

SCHEMA = '''
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS collections (
    id TEXT PRIMARY KEY, title TEXT, boost REAL, source TEXT, licence TEXT);
CREATE TABLE IF NOT EXISTS pages (
    url TEXT PRIMARY KEY, collection TEXT, lang TEXT, article TEXT, title TEXT, sha1 TEXT);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY, url TEXT, anchor TEXT, heading TEXT, text TEXT, vec BLOB);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, content='chunks', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE INDEX IF NOT EXISTS chunks_url ON chunks(url);
'''


def connect(path=DB_PATH):
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def sha1(s):
    return hashlib.sha1(s.encode()).hexdigest()


def put_page(db, collection, url, lang, article, title, digest, chunks, vecs):
    """Replace a page and its chunks (vecs: one row per chunk)."""
    drop_page(db, url)
    db.execute('INSERT INTO pages VALUES (?,?,?,?,?,?)', (url, collection, lang, article, title, digest))
    for c, v in zip(chunks, vecs):
        cur = db.execute('INSERT INTO chunks (url, anchor, heading, text, vec) VALUES (?,?,?,?,?)',
                         (url, c['anchor'], c['heading'], c['text'], v.astype(np.float16).tobytes()))
        db.execute('INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)', (cur.lastrowid, c['text']))


def drop_page(db, url):
    for rowid, text in db.execute('SELECT id, text FROM chunks WHERE url = ?', (url,)).fetchall():
        db.execute("INSERT INTO chunks_fts (chunks_fts, rowid, text) VALUES ('delete', ?, ?)", (rowid, text))
    db.execute('DELETE FROM chunks WHERE url = ?', (url,))
    db.execute('DELETE FROM pages WHERE url = ?', (url,))


# --- Search -----------------------------------------------------------------------------

def question_language(text):
    """en, es or fr when the question's common words say so, else None."""
    words = re.findall(r"\w+", text.lower())
    counts = {lang: sum(w in common for w in words) for lang, common in _COMMON.items()}
    best = max(counts, key=counts.get)
    ranked = sorted(counts.values(), reverse=True)
    return best if ranked[0] >= 2 and ranked[0] > ranked[1] else None


class Index:
    """The chunks in memory for searching; reload() after the file changes."""

    def __init__(self, path=DB_PATH):
        self.path = path
        self.reload()

    def reload(self):
        db = sqlite3.connect(f'file:{self.path}?mode=ro', uri=True)
        rows = db.execute('''SELECT c.id, c.url, c.anchor, c.heading, c.text, c.vec, p.collection,
                                    p.lang, p.article, p.title, k.boost
                             FROM chunks c JOIN pages p ON p.url = c.url
                             JOIN collections k ON k.id = p.collection ORDER BY c.id''').fetchall()
        self.meta = dict(db.execute('SELECT key, value FROM meta'))
        self.collections = [dict(zip(('id', 'title', 'boost', 'source', 'licence'), r))
                            for r in db.execute('SELECT id, title, boost, source, licence FROM collections')]
        db.close()
        self.ids = np.array([r[0] for r in rows], dtype=np.int64)
        self.rows = {r[0]: r for r in rows}
        dim = len(rows[0][5]) // 2 if rows else 0
        self.vecs = (np.frombuffer(b''.join(r[5] for r in rows), dtype=np.float16)
                     .reshape(len(rows), dim).astype(np.float32)) if rows else np.zeros((0, 0), np.float32)
        self.pages = {r[1] for r in rows}

    def _fts(self, query, n):
        # The question's words but common ones, quoted and OR'd: bm25 weighs rare words
        # (`pulldata`) up
        common = set().union(*_COMMON.values())
        words = [w for w in re.findall(r'\w+', query.lower()) if w not in common and len(w) > 1]
        if not words:
            return []
        q = ' OR '.join('"%s"' % w for w in dict.fromkeys(words))
        db = sqlite3.connect(f'file:{self.path}?mode=ro', uri=True)
        try:
            return [r[0] for r in db.execute(
                'SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?', (q, n))]
        finally:
            db.close()

    def search(self, query, k=8, collections=None, lang=None, mode='hybrid', qvec=None):
        """Best chunks first: [{score, similarity, url, anchor, title, section, collection,
        lang, text}]. mode: hybrid | vector | fts (eval.py compares them)."""
        if not len(self.ids):
            return []
        sims = (self.vecs @ (qvec if qvec is not None else embed([query])[0])) if mode != 'fts' else None
        fused = {}
        if mode in ('hybrid', 'vector'):
            for rank, i in enumerate(np.argsort(-sims)[:CANDIDATES]):
                fused[int(self.ids[i])] = fused.get(int(self.ids[i]), 0) + 1 / (RRF_K + rank)
        if mode in ('hybrid', 'fts'):
            weight = 1 if mode == 'fts' else FTS_WEIGHT
            for rank, cid in enumerate(self._fts(query, CANDIDATES)):
                fused[cid] = fused.get(cid, 0) + weight / (RRF_K + rank)
        pos = {int(c): i for i, c in enumerate(self.ids)}
        hits = []
        for cid, score in fused.items():
            r = self.rows[cid]
            if collections and r[6] not in collections:
                continue
            if lang and r[7] != lang:
                continue
            hits.append({'score': score * r[10], 'similarity': float(sims[pos[cid]]) if sims is not None else None,
                         'url': r[1] + (f'#{r[2]}' if r[2] else ''), 'page': r[1], 'title': r[9],
                         'section': r[3], 'collection': r[6], 'lang': r[7], 'article': r[8], 'text': r[4]})
        # The question's language first, or English for a language the guide doesn't have
        want = question_language(query) or 'en'
        for h in hits:
            if h['lang'] != want:
                h['score'] *= OTHER_LANGUAGE
        hits.sort(key=lambda h: -h['score'])
        # One language per article (that of its best chunk), and a few sections from each
        chosen, taken, out = {}, {}, []
        for h in hits:
            art = (h['collection'], h['article'])
            if chosen.setdefault(art, h['lang']) == h['lang'] and taken.get(art, 0) < PER_ARTICLE:
                taken[art] = taken.get(art, 0) + 1
                out.append(h)
        return out[:k]
