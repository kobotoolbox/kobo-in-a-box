# A fuller model benchmark, Gemma first: plan

Draft 2026-11-11. Companion to [STATUS.md](STATUS.md) (W1, W2, W4) and the user guide's
results (`site/index.html#results`). Results go in `remote/results/` and NOTES.md as now.

**Goal:** know which Gemma model, size and setting to put in each kit, from numbers on the
box's own tasks: transcription, translation, and KoboToolbox's analysis questions on
recordings, typed answers and photos, plus the agent and knowledge-base tasks. The
docs then show a comparison per task and a recommendation per hardware tier, instead of
one model. Other open models stay out except as one or two reference points.

---

## 1. Where we are

| Model | Quant | Measured on | Result |
|---|---|---|---|
| Gemma 4 E4B (+ Q8_0 projector) | Q4_0 | CPU rig (8 vCPU), H100, RTX 6000 Ada | the kit's model; every qual case right; translation chrF 59.4 |
| Gemma 4 26B-A4B | Q4_0 | H100 (all on GPU; 12 layers on GPU) | same scores as E4B; memory per tier |
| gpt-oss-120b | MXFP4 | H100 | agent candidate (W4), not a Gemma |
| Whisper large-v3-turbo | q8_0 | all three | 2.0% WER on FLEURS Spanish |

**The limit:** the test set is too easy to tell models apart. 10 qual cases, all right on
every model so far, 16 Spanish clips, and one photo. A fuller benchmark needs a harder,
wider test set first (section 3), or every Gemma will score 100% and only the speed will
differ.

## 2. What to test

### 2.1 Gemma 4 instruct models (ggml-org, Apache 2.0)

Q4_0 and Q8_0 sizes, from Hugging Face on 2026-11-11 (VRAM in use is about the file size
plus the context and, for the kit, Whisper's ~1.5 GB):

| Model | Q4_0 | Q8_0 | BF16 | Input | Why |
|---|---|---|---|---|---|
| E2B | 2.8 GB | 5.0 GB | 9.3 GB | text, image, audio (to check) | the smallest kit, the ARM light kit's optional AI, CPU speed |
| E4B | 4.6 GB | 8.0 GB | 15.1 GB | text, image, audio | the baseline |
| 12B | 7.2 GB | 12.7 GB | 23.8 GB | text, image, audio (to check) | the step up for a 16 GB machine |
| 26B-A4B (MoE) | 14.6 GB | 26.9 GB | 50.5 GB | text, image | field server; fast for its size (4B active) |
| 31B (dense) | 18.0 GB | 32.6 GB | 61.4 GB | text, image | the best Gemma that fits a 24 GB card at Q4 |

"To check": the repos are tagged any-to-any for E2B, E4B and 12B and image-text for the two
larger ones; the smoke test's Gemma-audio section shows whether audio input works.

### 2.2 Settings, per model

- **Quantization:** Q4_0 against Q8_0 for every size; BF16 for E2B and E4B as the ceiling
  (the larger BF16s only on an 80 GB card, if one comes).
- **Projector:** Q8_0 against BF16 (photos, paper forms, audio).
- **Image budget:** `--image-max-tokens` 280 / 560 / default on photos (E4B on CPU went from
  74 s to 36 s and 17 s, with a worse answer at 280: NOTES 2026-11-10).
- **Thinking:** off (as now) against on, for qual and agents; on leaked into answers in
  October (0 of 3), so on needs the reasoning kept apart.
- **Speculative decoding:** each repo has `mtp-` draft files (and `dflash-` for 26B and 31B).
  If llama.cpp's server uses them, they may cut CPU times a lot. First check the server
  version and flags, then E2B/E4B/12B on the CPU rig with and without.
- **Context:** 16k (as now) and the largest that fits, for the agent tasks.

### 2.3 Gemma specialists

- **TranslateGemma 4B, 12B, 27B** (Google; Gemma licence, not Apache). Only community GGUFs
  (mradermacher, bullerwins). Translation only: chrF on FLEURS against the instruct models
  of the same size. Check the licence terms for the kit, and record the files' checksums.
- **EmbeddingGemma 2** (ggml-org, Apache 2.0, 0.3 GB at Q8_0): the knowledge base's
  embeddings, against bge-m3 (W10), with `knowledge.sh eval`.

### 2.4 Reference points (not Gemma, kept small)

- Whisper large-v3-turbo stays the transcription baseline: Gemma's own audio input
  (E2B/E4B/12B) against it on the same clips.
- gpt-oss-120b's W4 agent numbers, already measured, as the bar for 26B and 31B.

## 3. The test set, harder and wider (before any GPU time)

- **Languages:** add FLEURS clips for a provisional pilot set until it's decided (STATUS,
  Open decisions): French, Portuguese, Swahili, Arabic, Hausa, Amharic (16 clips each, as
  Spanish). Transcription WER, and translation chrF into English and from English.
- **Qual on transcripts and typed answers:** from 10 cases to about 60. Each language. All
  four question types. Harder cases: answers that mention an option without choosing it,
  negations, numbers in words, two speakers. Each case gets its expected answer written by
  hand.
- **Photos:** from 1 to about 12 Wikimedia Commons photos (open licences, recorded as now):
  water points, latrines, shelters, damaged buildings, a crowded clinic, a blurred one. Plus a
  few pages of a filled paper form (W13's reading task).
- **Agents and dashboards:** the existing W4 task set and the 11 dashboard tasks, for 26B and
  31B (and 12B, to see whether a 16 GB kit can run the assistant).
- Keep the current cases unchanged, so new numbers still compare with October's.

## 4. Harness changes

1. **Recipes:** `gpu-tiers.sh` gets one per model/quant/setting (`e2b-q4`, `12b-q8`,
   `31b-q4-think`…), each naming its model file, projector and draft file.
2. **Downloads:** a `models.sh fetch <recipe...>` that fetches only what those recipes need
   (bootstrap's fixed list is the E4B kit's), with checksums. Fetch everything online, then
   `offline.sh on`, then run, as now.
3. **smoke-test.py:** the new languages and cases, per-language scores, tokens per second, time to
   first token, and the settings in the JSON.
4. **CPU runs:** the kit-sized models (E2B, E4B, 12B; with and without draft) on the CPU
   rig: a CPU-only kit is the cheapest kit.
5. **Results table:** a script that reads the JSONs into one table (model, quant, setting,
   hardware, each score, speed, VRAM, watts), the input of `site/charts.py` and the docs.

## 5. Order, and what it needs

| Phase | Where | What | Time |
|---|---|---|---|
| 0 | laptop | the test set (section 3), harness (section 4), a dry run with E4B | 2–3 days |
| 1 | RTX 6000 Ada 48 GB (`kobo-box-gpu`, up now; shared with the RISA test) | all of 2.1–2.3 up to 31B Q8_0, ~190 GB of downloads (432 GB free) | ~1 day of runs |
| 2 | CPU rig (restore `kobo-box-ai-snapshot`) | E2B / E4B / 12B, Q4 and Q8, with and without drafts | ~1 day |
| 3 | 80 GB card, if the poller gets one | BF16 26B and 31B (the ceiling), agents with long context | half a day |
| 4 | laptop | results table, charts, the docs: a comparison per task and a pick per tier | 1 day |

The 48 GB card covers nearly everything; 80 GB only adds the BF16 ceilings of the two large
models, where Q8_0 is usually within noise.

## 6. In the docs

- **Results** (`site/index.html#results`): per task (transcription, translation, qual by
  source, photos), the Gemma sizes side by side: score, time on the CPU kit and on a GPU,
  memory. The language breakdown, with what isn't good enough said plainly.
- **Choosing hardware:** a pick per tier (CPU only, 8 GB GPU, 16 GB, 24 GB, 48 GB), each with the
  model, quant and setting, and what it does better than the tier below.
- NOTES.md per run, as now.

## 6a. Progress

**Decided (2026-11-11):** the provisional six languages; TranslateGemma benchmarked but kept
out of the pack until its licence is reviewed; downloads on the GPU while phase 0 is built.

**Phase 0, built 2026-11-11** (branch `gemma-bench`):
- `eval/make-fleurs.py`: French, Portuguese, Swahili, Arabic, Hausa, Amharic, 16 clips each,
  the same 16 sentences in every language (8 of the Spanish set's, 8 more on its themes).
  FLEURS's dev and test clips are read by few speakers: Arabic, Hausa and Amharic only women,
  Portuguese only men.
- `eval/qual-cases.json`: 8 answers, 39 cases, in English, Spanish, French, Portuguese,
  Swahili and Arabic (the last two to check with native speakers). Hausa and Amharic answers
  still to be written by native speakers.
- `eval/photos.json` + `eval/photos/`: 12 Commons photos (public domain, CC0, CC BY, CC BY-SA;
  credits in the file), 36 cases.
- `smoke-test.py`: the extended sets, translation from English, scores per language
  (Whisper, Gemma audio, both translation directions), llama.cpp's timings, the run's
  settings and recipe, `--langs`. `gpu-tiers.sh`: 35 recipes, `MODE=cpu`, `--list`.
  `models.sh fetch|check|fleurs` (SHA-256 checked against Hugging Face). `ai.env`
  `LLM_EXTRA_ARGS` (empty on a kit). `eval/bench-table.py`: one table, CSV and Markdown.

**Dry run** (`e4b-q4`, RTX 6000 Ada, online): the harness works end to end and the new set
separates models: E4B 10/10 on October's cases but 65/75 on the extended ones (text 36/39,
photos 29/36), before fixing two of my expectations (answers that quote the respondent's
language; a screen count with no single right answer). Whisper turbo fails Hausa (WER 104%)
and Amharic (124%) and is weak on Swahili (41%), so translation from those transcripts falls
apart (chrF 18) while translation of the reference text holds (40-60): transcription, not
translation, is the gap for those languages; Gemma's own audio input is the comparison to
watch.

**Phase 1, done 2026-11-12** (RTX 6000 Ada, offline; NOTES.md and `remote/results/gemma-phase1/`):
what it says so far, for the kit:
- **E4B Q4_0 stays the kit's model:** 67/75 extended cases, no better at Q8_0 or BF16, 6.5 GB
  with Whisper, and the best Gemma audio for Swahili, Hausa and Amharic.
- **Above it, 26B-A4B Q4_0** (70/75, 18.6 GB, faster than 12B and 31B) for a 24 GB card;
  31B scores the same, slower. **12B is not a pick:** its audio loops in three languages and
  its Hausa translation from English fails.
- **Transcription by language:** Whisper for Spanish, French, Portuguese (and Arabic, close);
  Gemma audio for Swahili, Hausa, Amharic. Hausa and Amharic are still weak either way (WER
  25–56%), and from English poor at every size: to be judged by native speakers.
- **Settings:** image budget 560 is safe (280 isn't); thinking helps E4B on photos only, at 20×
  the time; projector BF16, TranslateGemma and drafts on a GPU add nothing.

**Phase 2, done 2026-11-12** (8 CPU cores, offline; NOTES.md, `remote/results/gemma-phase2/`):
the same scores as on the GPU (within one case); E4B 8.5 s a question (31 s for the first on
a photo), E2B 4.3 s, 12B 26.5 s; MTP drafts give nothing on a CPU either; Gemma audio is as
fast as Whisper (about real time), so transcribing Swahili, Hausa and Amharic with it costs
nothing. **E4B Q4_0 stays the kit's model on every tier without a 24 GB card.**

Next: the Hausa and Amharic qual cases (native speakers), the agent and dashboard tasks on
26B and 31B (phase 3, a GPU), EmbeddingGemma 2 against bge-m3 (knowledge base), and choosing
the transcriber per language in KPI's local backend (Whisper for es/fr/pt, Gemma for
sw/ha/am).

## 7. Open decisions

- **Languages:** the provisional set above, or the pilot's own once chosen (each one is a
  FLEURS manifest and its qual cases).
- **TranslateGemma's licence** (Gemma terms) for a kit partners use, and community GGUFs
  in the pack.
- **The 80 GB poller:** keep it running for phase 3, or stop it (the 48 GB card covers
  phases 1–2).
- **Sharing `kobo-box-gpu`** with the RISA test: phase 1 runs when it's free, or on a second
  48 GB droplet.
