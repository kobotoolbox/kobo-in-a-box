# Status and next steps

Living reference for where the work stands. The overall plan and workstreams (W1–W7)
are in [PLAN.md](PLAN.md); per-run results are in [remote/results/NOTES.md](remote/results/NOTES.md).

## Where we are (2026-10-28)

- **Rig:** CPU droplet (`s-8vcpu-32gb-amd`) with Kobo (`kobo-setup.py`), Gemma 4 E4B and
  Whisper large-v3-turbo, parked as `kobo-box-ai-snapshot` in ams3. GPU sizes (RTX 4000/6000
  Ada, L40S) have been out of stock in every region.
- **Works offline:** Kobo, both models, and KPI → `http://llm:8080` / `http://whisper:8080`.
- **Findings so far (8 vCPU, CPU only):**
  - Qual analysis passes KPI's parser 3/3 *only with thinking off* (`LLM_THINKING=false`).
    `--reasoning-budget 0` leaks reasoning into the answer and fails every case.
  - Translation ~2 s and qual 6–11 s per call: usable for KPI's AI features.
  - Whisper ~2% WER on FLEURS Spanish. Speed is ~13–15 s per 30 s window with the language
    set (~2× real time on long audio); auto-detect doubles that on short clips. Usable
    for overnight batches on CPU, slow for interactive use.
  - Prompt processing ~31 tokens/s: CPU-only can't run agents (10–20k-token prompts).

## Next steps

### 1. Spanish benchmark (W1) ✅ done 2026-10-28
Whisper and Gemma audio ~2% WER on FLEURS Spanish; translation correct (chrF ~59, see
[NOTES](remote/results/NOTES.md) for why that's not low); whisper ~13–15 s per 30 s window
with `language` set. All passes offline.

After restoring a snapshot the droplet has a new IP: run
`cd /root/kobo-install && python3 run.py` once so Kobo's hostnames follow it.

### 2. W2: KPI local NLP backend (2–4 weeks)
- [x] Clone `kobotoolbox/kpi` (`main`) to `~/code/kpi`; branch `local-nlp-backend`
- [x] Read `kobo/apps/subsequences/`: `AutomaticBedrockQual.get_response_from_llm()`, the
      Google transcription/translation services, and how a service is selected
- [ ] `NLP_BACKEND=local` setting; qual analysis → OpenAI-compatible `http://llm:8080`
      (code + tests committed, `f4b670fce`; tests not yet run)
- [ ] Translation → `llm`; transcription → `whisper` as Celery tasks
- [ ] Seed language tables for the pilot languages
- [ ] Deploy the branch to the CPU droplet and test through the UI while offline

How KPI wires NLP (as of kpi `bb33f41a8`):
- **Qual** (`actions/automatic_bedrock_qual.py`) runs synchronously inside the request,
  so its timeout must stay under uWSGI's 120 s harakiri. The request body is already
  OpenAI chat format, so llama-server takes it almost as-is.
- **Transcription / translation** (`actions/automatic_google_*.py`) go through
  `get_nlp_service_class()` → a service with `process_data()` returning
  `in_progress` / `complete` / `failed`; `allow_async=True` makes Celery poll while
  `in_progress`. A local service plugs in at the same place.
- **Access:** Constance `ASR_MT_INVITEE_USERNAMES` (`*` = everyone) gates the transcribe
  and translate buttons. Usage limits only apply with Stripe enabled, so self-hosted is
  unlimited. Automatic qual has no extra frontend gate.
- **Action IDs stay the same** (`automatic_bedrock_qual`, `automatic_google_*`), so the
  frontend needs no changes.

### 3. W3: kobo-mcp offline profile (2–3 days, parallel with W2)
- [ ] Clone kobo-mcp
- [ ] Allow `http://` only for `EXTRA_KOBO_HOSTS` (`src/kobo_mcp/servers.py`)
- [ ] Offline config profile; recommended OpenCode permissions (deny deletes, ask before writes)

### 4. GPU tiers (W1, when stock returns)
- [ ] Check stock each session; when available, fresh `./provision.sh` (not the CPU snapshot)
- [ ] 8 GB and 20 GB recipes from the README, plus Gemma 4 26B-A4B, with power figures

## Open decisions

- **Pilot languages** (3–6). Each one becomes an `eval/fleurs-<config>.tsv` manifest.
- **Mock interviews:** ask the pilot partner for 5–10 per language, recorded on field phones
  through a Kobo audio question. FLEURS is clean read speech, so it only gives a best case.
- **KPI team:** involve them now or after a working prototype (the aim is to merge upstream).
- **kobo-mcp repo location.**
