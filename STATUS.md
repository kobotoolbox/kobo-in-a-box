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
- [x] `NLP_BACKEND=local` setting; qual analysis → OpenAI-compatible `http://llm:8080`
      (kpi `f4b670fce`).
      `remote/e2e-nlp.py` passes online and offline: 3/3 correct, 10–17 s each
      through the full API (cold).
- [x] Translation → `llm` (kpi `353a22dc1`): `LocalTranslationService`, same interface
      as Google's, only runs in a Celery worker (or with eager Celery) so slow boxes
      don't hit the request timeout. Qual and translation share
      `integrations/local/client.py`. E2E: the PATCH returns `in_progress`, a worker
      translates, and the result is a faithful Spanish translation (online only so far;
      another agent was using the droplet, so no offline run).
- [x] Transcription → `whisper` (kpi `5f521db04`): `LocalTranscriptionService` posts the
      transcoded audio to `LOCAL_WHISPER_URL`; worker-only like translation. E2E with a
      FLEURS Spanish clip through an OpenRosa audio submission: 0% WER (online only).
- [x] Whole `kobo/apps/subsequences/` suite on kpi `main` + the three commits: 425 passed
      (`testing`), 414 passed (`testing_no_stripe`), no failures
- [x] E2E offline (2026-10-28, restored snapshot): with egress confirmed blocked, qual 3/3,
      translation via Celery and transcription (0% WER) all pass, same as online
- [ ] Build a kpi image from the branch and run it instead of the backport
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

Testing W2 on the CPU droplet (state kept in the snapshot):
- **Unit tests:** `remote/kpi-test.sh` runs `kobo/apps/subsequences/` (with both
  `testing` and `testing_no_stripe`, as CI does) against `/root/kpi-src`
  (kpi `main` + the branch as a patch) in a `python:3.12` container with PostGIS and
  Redis, as CI does. It needs a JRE (pyxform validates forms with Java), which GitHub's
  runners have preinstalled. To update the code: send `git format-patch` from
  `~/code/kpi` and `git am` it there (a `git archive` of the partial clone is very slow).
- **Running Kobo is release `2.026.37c`,** which predates `main`'s qual refactor, so the
  branch can't be dropped in. A backport of the same changes (`/root/kpi-e2e/`) is
  mounted into the `kpi`, `worker` and `worker_low_priority` containers by
  `/root/kobo-docker/docker-compose.frontend.custom.yml` (with `NLP_BACKEND=local`;
  `use_frontend_custom_yml` is on in `.run.conf`). The workers need it too because they
  run translation. Remove both to get stock KPI back. For a real deploy, build a kpi
  image from the branch instead.
- **Shared droplet:** another agent works on the same droplet (library / edge nginx on
  port 80, Kobo's nginx on 8080). Only one person runs `offline.sh` at a time, nothing
  runs during `kobo-setup.py --reconfigure`, and timings taken while their builds run
  aren't benchmarks.
- **E2E:** `remote/e2e-nlp.py` covers qual, translation and transcription. Run it as
  `e2e`, a regular user, password in `/root/e2e-user.pw`.
- **Firewall:** this network's outgoing IP rotates (several changes on 2026-10-28).
  When SSH times out, compare `curl -4 ifconfig.me` with the firewall's inbound rules and
  add the new IP with `doctl compute firewall add-rules` (don't replace the list: the
  other agent's IPs are in it too). On a mobile connection (carrier NAT, e.g.
  `92.184.112.x`) the address can change within minutes; allowing SSH only from that
  /24 for the session works, and the next `provision.sh` resets the rules anyway.

### 3. W3: kobo-mcp offline profile ✅ done 2026-10-28 (droplet-tested, online and offline)
kobo-mcp branch `w3-offline-box` in `~/Desktop/work/repos/kobo-mcp` (local, not pushed;
962 unit tests pass, ruff clean):
- [x] `HTTP_KOBO_HOSTS` (`9023390`): plain http only for hosts also in `EXTRA_KOBO_HOSTS`
      (checked at startup). Bare `kf.kobo.local` gets `http://`; the token goes over http only
      to such a host; the connection guard trusts port 80 for them only. Sign-in page links
      use each server's scheme.
- [x] Offline config: email is already off unless `RELAY_KEYS` + `RESEND_API_KEY` are set
      (documented, no code). `DASH_KOBO_HOSTS` (`b89e94f`) replaces the hardcoded kf/eu
      dashboard servers. **kobo-dash still needs its half** (PLAN 3h): `ALLOWED_SERVERS` plus
      accepting `http://` base URLs in `kobo.py`, which kobo-mcp now sends in `srv`.
- [x] `TOOL_PROFILES` (`9d705ce`): `analysis`, `forms`, `data`, `sharing`, `integrations`,
      `dashboards`, `deletes`, `all`, and/or tool names; always with whoami, list_projects,
      get_project, describe_form. All 73 tools ≈ 38k tokens; `analysis` ≈ 7k;
      `analysis,forms,data` = 32 tools ≈ 15k. Deletes only via `deletes`. A test fails if a
      new tool isn't in a profile. Follow-up: `INSTRUCTIONS` (~1.3k tokens) still describes
      every tool.
- [x] OpenCode config: `remote/agents/opencode.json` (+ README): delete tools off via the
      documented `tools` map, `kobo_*` → ask with the 36 read-only tools allowed, web tools
      denied, no autoupdate. ⚠ Whether `permission` keys apply to MCP tools is unverified in
      OpenCode's docs: test in W4.
- [x] Droplet check: `remote/agents/run-mcp-check.sh` builds kobo-mcp's image on the box and
      runs `mcp-check.py` against it in HTTP header mode with the box settings. 19/19 pass
      online and with egress blocked: `/healthz`, 32 tools and no delete tools, whoami on
      `http://kf.kobo.local`, reads (projects, form, stats, summary, submissions), a
      reversible write (`set_validation_status` → on_hold → restored), and refusals of
      foreign servers and of http to non-HTTP hosts.
- Not done here: OAuth sign-in (`/login`, `mcp.kobo.local` behind the edge) and an actual
      OpenCode client; both belong to W4.

### 3b. W10: local knowledge base (PLAN 3i), can start now
- [ ] `remote/knowledge/`: support-bot chunker, bge-m3 on llama-server, pgvector + FTS, MCP server; port its eval cases

### 4. GPU tiers (W1, when stock returns)
- [ ] Check stock each session; when available, fresh `./provision.sh` (not the CPU snapshot)
- [ ] 8 GB and 20 GB recipes from the README, plus Gemma 4 26B-A4B, with power figures

## Open decisions

- **Pilot languages** (3–6). Each one becomes an `eval/fleurs-<config>.tsv` manifest.
- **Mock interviews:** ask the pilot partner for 5–10 per language, recorded on field phones
  through a Kobo audio question. FLEURS is clean read speech, so it only gives a best case.
- **KPI team:** involve them now or after a working prototype (the aim is to merge upstream).
- **kobo-mcp repo location.**
