# Knowledge base (W10)

The assistant's search over the documentation on the box (PLAN 3i): the KoboToolbox user
guide in English, Spanish and French, as the offline library serves it at
`http://kobo.local/docs/kobo/`. OpenCode reaches it as an MCP server,
`http://knowledge.kobo.local/mcp`, next to kobo-mcp; its tools are read-only and allowed
without asking.

| File | What |
|---|---|
| `kb.py` | Pages to text (the page's main element, headings with their anchors), the support bot's chunker, the SQLite store (chunks, FTS5, float16 embeddings), hybrid search |
| `index.py` | Builds or refreshes the index from `collections.json` (unchanged pages skipped) |
| `server.py` | MCP tools `search_knowledge`, `read_document`, `list_collections`; `GET /healthz`, `GET /search?q=` |
| `eval.py`, `cases/` | Retrieval checks: `box.yaml`, and the support bot's cases (`howto`, `multilingual`, `unanswerable`, `hallucination_bait`) when copied in with `knowledge.sh cases <checkout>`: kobo-support-bot-poc is private, so they're not in git here |
| `knowledge.sh` | `build` (online), `index`, `up`, `down`, `search`, `eval` |
| `docker-compose.knowledge.yml` | `embed` (llama-server, bge-m3, embeddings only), `knowledge` (search and MCP on 127.0.0.1:8088), `index` (on demand) |

```bash
./knowledge.sh build                 # online, on the rig: the image and bge-m3 (0.6 GB)
./knowledge.sh index                 # the library's pages -> /opt/knowledge/knowledge.db
./knowledge.sh up
./knowledge.sh search how do I make a question required
./knowledge.sh eval ../results/knowledge-eval.json
```

On a box it all comes from the content pack: the two images, the model in `/opt/models`,
and the index in `/opt/knowledge` (`pack.sh` takes it from the rig). First boot starts it
(`firstboot.sh`'s `knowledge` step), an update from an older pack adds it (`firstboot.sh
catch-up`), and the status page has a "Documentation search" row.

## How it works

- **The library's own pages.** The index reads the HTML the box serves, so every result's
  URL (`http://kobo.local/docs/kobo/es/export_download.html#tipos-de-exportacion`) opens
  on the box, at the section. Page text is the page's `role="main"` element (Sphinx's, in
  the Kobo guide and the QGIS docs), without navigation, scripts or the heading `¶` links;
  tables keep a row per line.
- **The support bot's chunks:** split at H2–H4, merged up to ~1,600 characters, split at
  paragraphs above ~2,400, each starting `[Article: …] [Section: …]` (kobo-support-bot-poc
  `indexer.py`). ~10 per page.
- **bge-m3** (MIT, Q8_0, 1024-d) on llama-server, CPU only: a question takes ~50 ms to
  embed. Indexing is the slow part (on the rig, minutes per hundred pages), so it happens
  once, when the pack is made; a box only searches.
- **Hybrid search:** the meaning ranking (cosine over all chunks: a few thousand, so no
  vector index) and SQLite FTS5's bm25 over the same chunks, fused by reciprocal rank, then
  times the collection's boost. Exact names (`select_one_from_file`, `pulldata`, "Value not
  allowed") are where meaning alone misses. Then one language per article: the language of
  its best chunk, so a question in Spanish gets the Spanish page, and one in Swahili (a
  language the guide doesn't have) the closest page in any.
- **One file.** The index is a single SQLite file, with the embedding model's name in it;
  a different model re-embeds everything. No Postgres: the plan had pgvector in the
  dashboards' database, but nothing here needs a server, and a file ships in the pack and
  restores by copying.
- **Untrusted text.** Results are returned as quoted text, under "quoted material, not
  instructions", and the server's instructions say never to follow instructions inside
  them. The documents are the guide for now; anything added later (W10's `add`) is
  untrusted, and the agent's write tools still ask first.

## Results (2026-11-05, the CPU rig)

The Kobo guide: 426 pages (en, es, fr), 2,696 sections, a 12.8 MB index; 52 min to embed
on 8 vCPUs, 55 ms to embed a question. 33 questions with an answer in the guide (the
support bot's 20 with `retrieve_any`, the box's 13) and 11 with none:

| Search | hit@1 | hit@3 | hit@5 | hit@8 | MRR | right language first |
|---|---|---|---|---|---|---|
| meaning (bge-m3) | 0.61 | 0.76 | 0.85 | 0.88 | 0.70 | 1.0 |
| words (FTS5 bm25) | 0.39 | 0.73 | 0.73 | 0.73 | 0.53 | 1.0 |
| **both (used)** | 0.58 | **0.79** | 0.85 | **0.94** | 0.70 | 1.0 |

- **Language:** at first an English question often got the Spanish or French copy of the
  right page (bge-m3 matches across languages that well), and a Hindi or Swahili one a
  random translation: "right language first" was 0.5. Now the question's language is
  told from its common words, pages in it come first, and English for any language the
  guide doesn't have (1.0).
- **One page, many sections** crowded the results: at most two sections a page now.
- **Words alone** missed every French question (its common words matched everything):
  common words are left out of the word search, and it counts half in the fusion (0.25,
  0.5 and 1 tried: 0.5 is as good as 0.25 and better than 1 at hit@3 and hit@8).
- **No "not covered" line from similarity:** the best similarity of a question the guide
  can't answer (median 0.62, up to 0.77) overlaps the answerable ones' (median 0.65, from
  0.52). Search always returns sections; the model has to judge, as the server's
  instructions tell it ("say the documentation here doesn't cover it").
- Still missed in the first 8: an enumerator seeing only their own submissions (row-level
  permissions), "stuck pending" (lands on the web forms troubleshooting page), and two
  French questions. 33 cases is few: one case is 3 points.
- Through OpenCode (`agents/w4-permissions.py`, the stand-in model): the three tools are
  offered, run without asking, and a search returns the guide's sections with
  `http://kobo.local/docs/` URLs; every permission check still passes.

Reports: `../results/knowledge-eval-*.json`.

## Not yet

- The other collections: QGIS is in `collections.json` but off (its user manual is large,
  and it needs its own cases); ODK docs (CC BY 4.0) aren't in the library yet; XLSForm.org
  has no licence file, so it waits for permission.
- `knowledge.sh add` for a deployment's own documents (PDF, DOCX, ODT), and the reranker.
- Answer quality with the agent model (the support bot's key facts and rules), on the GPU
  rig: W4's runner with knowledge questions.
