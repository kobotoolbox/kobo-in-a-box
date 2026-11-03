# Status and next steps

Living reference for where the work stands. The overall plan and workstreams (W1–W7)
are in [PLAN.md](PLAN.md); per-run results are in [remote/results/NOTES.md](remote/results/NOTES.md).

## Where we are (2026-11-03)

- **Rigs:** the CPU rig (`s-8vcpu-32gb-amd`: Kobo, the KPI backport, kobo-mcp, OpenCode, test
  data) is parked as `kobo-box-ai-snapshot` in ams3. Its Kobo is 2.026.37d (since
  2026-11-02, with the backport rebased onto it) on the fixed address
  (`BOX_IP=10.254.254.254`) with W12's units installed, so a restore needs no `run.py`; it
  holds the test pack signing key (`/root/kobo-pack-signing.key`); `/root/fake-usb.img` is an exFAT `KOBOBACKUP` drive for tests
  (`losetup -fP /root/fake-usb.img` plugs it in). GPU work runs on a separate H100
  (`NAME=kobo-box-gpu`), deleted after each session: the 20–48 GB GPU sizes stay out of stock.
- **Proven offline, end to end:**
  - KoboToolbox, the offline library and the edge proxy (W8);
  - KPI's automatic qual, translation and transcription on local models (W2, branch
    `local-nlp-backend`; 425/414 tests pass);
  - kobo-mcp against the box's Kobo over plain http, with a tool profile (W3);
  - OpenCode agents doing field tasks through kobo-mcp (W4).
  - Optional case management (W11): EspoCRM at `cases.kobo.local`, with Kobo submissions
    opened as routed cases by a bridge (health referral scenario, 27/27 online and offline).
  - A box that runs itself (W12), everything that doesn't need the hardware: Kobo on a
    fixed internal address, AI settings from the hardware, encrypted backups by plugging in
    a `KOBOBACKUP` drive, restored on the same box or onto a replacement (EspoCRM
    included), the status page, a watchdog for hung model servers; kits made from a signed
    content pack (offline factory install, then a first power-on that gives each box its own
    name, passwords, case management and label card: 17 min), and updates by plugging in a
    newer signed pack (37c → 37d in 4 min, data kept).
- **Models:**
  - KPI batch work: Gemma 4 E4B with thinking off (qual 3/3, translation chrF ~59) and
    Whisper large-v3-turbo (~2% WER, Spanish). Together 6.3 GB: they fit an 8 GB GPU.
  - Agent: gpt-oss-120b (24/30 tasks, all writes right; 63 GB, so the 128 GB box only).
    Gemma 4 26B-A4B (22/30) is fine for questions, not for changing data.
- **CPU only** (8 vCPU): KPI's AI features are usable (translation ~2 s, qual 6–11 s,
  transcription ~2× faster than real time on long recordings, about clip length on short ones; fine overnight). Agents aren't: OpenCode's ~21k-token prompt
  at ~31 tokens/s means minutes per step.

**Next, in order:**
0. **W12, what can be done before the hardware:** done (2026-11-02): the status page and
   watchdog, the signed content pack with `install.sh --pack` (the factory step),
   `firstboot.sh` with case management and the label card, restores onto a replacement box,
   and updates from a newer pack. What's left needs the box: hotspot + local DNS, the
   autoinstall USB with LUKS + TPM, low-battery shutdown (`remote/box/README.md`).
0b. **W11:** done but for what needs the box or the pilot: follow-ups in KoboCollect on a
   phone (with the hotspot), an offline run of the newer parts, agent tasks for the cases
   tools (GPU rig), and the pilot's languages (site/cases.html has the user guide).
1. **W5 hardware:** buy the Strix Halo 128 GB dev unit and re-run the same tests on it
   (`gpu-tiers.sh` equivalents, `w4-run.py`), at full power and capped. This decides the
   kit; everything else so far is a cloud stand-in.
2. **W4 follow-ups:** confirm OpenCode's `ask` rules really apply to the Kobo write tools
   (the runner's `--auto` approves asks, so W4 didn't test it; check OpenCode's permission
   log), shorter agent prompts (fewer built-in tools, smaller profiles), guidance about each
   form (the enumerator-question mistakes), multi-user sign-in through kobo-mcp's OAuth,
   OpenWork, and a per-process DNS check offline.
3. **W9:** done on the rig (2026-11-03, `remote/dash/`); left: a real basemap once the
   pilot countries are chosen, scoring the 11 dashboard tasks on the GPU rig, offline
   `desk_review` (W10), proposing kobo-mcp's `w9-box` settings upstream.
4. **W2 to finish:** a KPI image from the branch, the pilot languages' tables, and
   proposing the change upstream (talk to the KPI team).
5. **W10 knowledge base**, and the W12 steps that need the box: hotspot + local DNS,
   autoinstall USB with LUKS + TPM.
6. **Decisions needed:** the pilot languages and partner, mock interviews recorded on field
   phones (FLEURS is a best case), and when to involve the KPI and kobo-mcp maintainers.

## Next steps

### 1. Spanish benchmark (W1) ✅ done 2026-10-28
Whisper and Gemma audio ~2% WER on FLEURS Spanish; translation correct (chrF ~59, see
[NOTES](remote/results/NOTES.md) for why that's not low); whisper ~13–15 s per 30 s window
with `language` set. All passes offline.

After restoring a snapshot the droplet has a new IP. Snapshots from 2026-10-30 on don't care
(Kobo is on the fixed address, W12); older ones need `cd /root/kobo-install && python3 run.py`.

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
- **Web sign-in fails offline for unverified emails (found 2026-10-30).** KPI runs with
  `ACCOUNT_EMAIL_VERIFICATION = mandatory`, so signing in as a user whose email isn't
  verified makes allauth send a confirmation mail; with no mail server the login POST
  returns 500. API tokens are unaffected, which is why the tests never hit it. On the rig
  `e2e`'s `EmailAddress` is now marked verified. Fix in `kobo-setup.py` (`offline_mail`):
  `ACCOUNT_EMAIL_VERIFICATION=none` and KPI's file email backend, in the env file that
  sets `EMAIL_BACKEND`. **Not run yet** (the rig was parked): next session, run
  `kobo-setup.py --reconfigure`, check which file it changed, and sign in in a browser as
  a new user with an unverified email, with `offline.sh on`.
- **Homepage screenshots:** `site/kobo-shots.py` runs in the Playwright image on the
  droplet (command in its docstring, plus `--add-host` for the four `*.kobo.local` names).
  The box's own pages (status page, label card) come from `site/box-shots.py`, which
  renders them on the laptop with the box's code and made-up values, so no real box's
  passwords end up in a screenshot.
- **Firewall:** this network's outgoing IP rotates (several changes on 2026-10-28).
  When SSH times out, compare `curl -4 ifconfig.me` with the firewall's inbound rules and
  add the new IP with `doctl compute firewall add-rules` (don't replace the list: the
  other agent's IPs are in it too). On a mobile connection (carrier NAT, e.g.
  `92.184.112.x`) the address can change within minutes; allowing SSH only from that
  /24 for the session works, and the next `provision.sh` resets the rules anyway.

### 3. W3: kobo-mcp offline profile ✅ done 2026-10-28 (droplet-tested, online and offline)
kobo-mcp branch `w3-offline-box` in `~/Desktop/work/repos/kobo-mcp`, merged into `main` and
pushed 2026-11-03 (962 unit tests pass, ruff clean):
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

### 3a. W9: dashboards on the box (PLAN 3h), server-side settings done 2026-10-29
kobo-dash branch `w9-offline-box`, in a separate worktree `~/Desktop/work/repos/kobo-dash-w9`
(the main `kobo-dash` checkout has someone's uncommitted map/theme work on `main`; untouched).
Merged into `main` and pushed 2026-11-03. Whole suite: 838 passed with the viewer built (`npm run build`);
without the build, `test_indexing_and_embedding` fails and 4 tests skip, on `main` too.
- [x] Kobo over http (`40002c7`): `ALLOWED_SERVERS` may list `http://kf.kobo.local`; the token
      goes over http only to that exact server. Also fixes a gap: a scheme-switching `next`
      link on an https server now stays https.
- [x] Tiles over http (`661b22b`): an http `TILE_URL` is accepted only when `PUBLIC_URL` is
      http too (an https page would block it as mixed content).
- [x] `BOUNDARIES_DIR` (`a9e8d00`): "get administrative areas" reads pre-fetched layers and
      never calls geoBoundaries. `scripts/fetch_boundaries.py OUT KEN UGA --levels ADM0,ADM1,ADM2`
      fills it online (checked live: Lesotho ADM1, 10 areas, 0.2 MB, with its credit line).
- [x] `LOCAL_EVIDENCE_ORIGINS` (`7bd2143`): evidence may cite e.g. `http://kobo.local/...`; the
      viewer links http sources only on http pages. kobo-mcp's `save_evidence` wording matches
      (kobo-mcp `f727031`, on `w3-offline-box`).
- [x] **On the box (2026-11-03, `remote/dash/`, see its README):** Postgres 17, kobo-dash
      web + poller and the box's one kobo-mcp as a compose project; edge routes `dash.` and
      `mcp.kobo.local` (live updates unbuffered) and `kobo.local/tiles/`; per-box keys;
      `dash.sh account <user>` makes the view-only `<user>_dash` account and saves its
      token in kobo-dash (no token pasted by hand); `dash.sh boundaries` / `tiles` fill the
      content pack's new `maps/` folder; `firstboot.sh` step `dash`, status page row,
      backups. OpenCode now reaches kobo-mcp as `mcp.kobo.local` through the edge and
      waits for its health check (kobo-mcp moved out of `agents/`).
- [x] kobo-mcp branch `w9-box` (`c11c4e9`, `3fe5b14`; 968 unit tests pass): `MCP_OAUTH=false`
      (the MCP SDK refuses an http OAuth issuer, so `OAUTH_KEYS` crashed kobo-mcp on
      `http://mcp.kobo.local`; the sign-in page for kobo-dash doesn't need it, and the agent
      uses header mode) and `PUBLIC_KOBO_SERVERS=false` (the sign-in page offered Global and
      EU, unreachable offline).
- [x] `e2e-dash.py` on the rig, real Kobo: 23/23 online; 28/28 offline with `--maps LSO`
      (sign-in, dashboard made by kobo-mcp's tools, poller, public/offline, a new
      submission reaching an open page's event stream in ~66 s, Lesotho's regions from the
      maps folder, the box's basemap). Packet capture: nothing addressed outside the box
      (a deliberate connection showed up). Reboot: all back, OpenCode with `kobo` and
      `cases` connected. Backup/restore, also onto a box with other keys. 1.3 GB of
      images, ~255 MB RAM idle.
- [x] W4: 11 dashboard tasks (`dash-*`) and an `after: dashboard` check from kobo-dash's
      database (a widget or filter must be new); checked against a real dashboard, not
      yet run with an agent model.
- [ ] Left: a basemap rendered for the pilot region (made-up tiles in the test); scoring
      the dashboard tasks (GPU rig); offline `desk_review` (W10); upstream proposals; the
      sign-in page labels the box's Kobo "kf.kobo.local — kf.kobo.local" (cosmetic).

Box settings for kobo-dash: `ALLOWED_SERVERS=http://kf.kobo.local`, `PUBLIC_URL=http://dash.kobo.local`,
`MCP_URL=http://mcp.kobo.local`, `TILE_URL=http://kobo.local/tiles/{z}/{x}/{y}.png` (or empty),
`BOUNDARIES_DIR=/data/boundaries`, `LOCAL_EVIDENCE_ORIGINS=http://kobo.local` (all in
`remote/dash/docker-compose.dash.yml`).

### 3b. W10: local knowledge base (PLAN 3i), can start now
- [ ] `remote/knowledge/`: support-bot chunker, bge-m3 on llama-server, pgvector + FTS, MCP server; port its eval cases

### 3c. W4: agents on the rig ✅ first runs 2026-10-29
`remote/agents/`: agent model (own llama-server), kobo-mcp and OpenCode 1.19.5 as a compose
profile; `w4-fixture.py` (seeded survey, known answers), `w4-tasks.json` (30 tasks),
`w4-run.py` (runs each through `opencode run`, scores tools, answers and Kobo's state).
Details in [NOTES](remote/results/NOTES.md).
- [x] Gemma 4 26B-A4B: **22/30**. Safety 3/3, breakdowns 7/7, but writes 0/2 (a 211-call
      loop), 5 empty answers, counts from paged submissions. Fine for reading, not for writes.
- [x] gpt-oss-120b: **24/30**. Writes 2/2, forms 2/2, no empty answers; misses were field
      confusion (`_submitted_by` vs the Enumerator question, submission vs interview date).
- [x] Offline: 8/8 with the internet blocked (model over the VPC), OpenCode cold-started
      offline; no failed outbound attempts in OpenCode's or kobo-mcp's logs.
- [ ] Per-process DNS capture offline; OpenWork; multi-user (one OpenCode per user vs shared,
      OAuth sign-in instead of the test rig's header token)
- [ ] Shorter prompts: OpenCode's first request is ~21k tokens, resent each step (~80k per
      task). Try fewer built-in tools / a smaller profile, and measure prompt speed on W5 hardware
- [ ] Task fixes worth trying: tell the model the form's own Enumerator question exists
      (skill or instructions), and re-run the write tasks on Gemma with a skill
- Session: CPU rig + H100 (`NAME=kobo-box-gpu SSH_PORT=443`), ~50 min of H100 (~$4); H100
  deleted, CPU rig parked (its snapshot now has the OpenCode image and the agent stack).

### 3d. W11: case management on the box ✅ built and tested 2026-10-30
`remote/espocrm/` ([README](remote/espocrm/README.md), PLAN 3j): EspoCRM 9.3.11 + MariaDB +
scheduler + a Kobo → EspoCRM bridge, started with `espocrm.sh up` (optional). Modelled on
Ponto's local EspoCRM testing (`~/code/ponto/infra/espocrm`), with per-box secrets.
- [x] Template-driven setup (`templates/health-referral.toml`): teams, roles (case worker /
      supervisor / bridge), Case fields, case page and list layouts; version checks off
- [x] Bridge polls KPI's data API (cursor on `_id`, dedupe on uuid); 9 unit tests
- [x] Scenario: CHW household visits (danger signs, MUAC, suspected cholera, pregnancy
      danger signs) → referral coordinators, nutrition (OTP), surveillance; made-up data
- [x] Rig (CPU, real Kobo through the edge): `e2e-espo.py --edge` **27/27 online, 27/27
      offline** incl. an offline cold start; cases within 16–32 s; no duplicates; roles hold;
      no external assets; packet capture on the stack's network: 0 outbound packets
      (a control connection was captured). Laptop with a fake Kobo: 26/26
- [x] Footprint: 1.6 GB images, ~330 MB data, ~200 MB RAM idle
- [ ] Phase 2: status back to Kobo, edited submissions, an EspoCRM MCP for the agents, UI
      languages (EspoCRM has no Swahili), images in the content pack, secrets via `firstboot.sh`
- Found on the rig: `/root/kobo-install/.run.conf` still had a previous droplet's IP
  (`local_interface_ip` 209.38.102.192), which `agents.sh` passes to kobo-mcp as `kf.kobo.local`.
  The bridge uses `host-gateway` instead. Fixed for good by W12's fixed address (3e below). Port 8081 is the batch LLM's, so EspoCRM is on 8084.
- The rig is still running with the stack up (`espocrm.sh down` to stop it). SSH from
  92.184.112.0/24 was added to `kobo-box-ai-fw` for this session.

- [x] **Bridge ledger** (2026-11-03, PLAN 3j steps 0–1): EspoCRM answers a choice it doesn't
      have with a 400 naming the field (and silently drops an unknown field). A refused
      submission is now recorded in `bridge.sqlite` and retried (1 min, 10 min, 1 h, 6 h; at
      once when the template or form version changes), and the rest carry on; the state is
      on the host (`/var/lib/kobo-box/bridge`), in backups, on the status page, and in
      `espocrm.sh failed`. 16 unit tests; `e2e-espo.py --ledger` 35/35 on the rig. EspoCRM's
      admin password is now four groups of four (a fresh install signs in with it).

- [x] **Choices from the deployed form** (2026-11-03, PLAN 3j step 2): the template no longer
      copies the form's choices (~40 lines gone); setup and the bridge read them from each
      project's deployed version, options are only added, and `kobo-box-cases-setup.timer`
      runs `espocrm.sh setup --if-form-changed` every 10 min, so a zone added in Kobo
      reaches EspoCRM with no one on the box and refused visits retry at once. The bridge
      opens no case while a mapped field is missing (EspoCRM would drop the value): on a new
      box, visits wait until setup has made the fields. 22 unit tests; e2e 38/38 on the rig.

- [x] **Follow-up visits update their case** (2026-11-03, PLAN 3j step 3): a follow-up form
      picks the case from `open_cases.csv`, which the bridge keeps on it (open cases, minimal
      columns, at most every 15 min); each follow-up updates exactly one case (else the
      ledger), only the listed fields and the status, as `kobo-followup` (edit those only,
      no create), with a note on the stream; closed cases get the note only. e2e 53/53 on
      the rig. Found on the way: a 10-minute timer that does its job makes a test's
      "undo" come back (the earlier run's form still had the test zone): tests now use a
      zone of their own. Not tested on a phone yet.

- [x] **W11 phase 2** (2026-11-03): edited Kobo submissions update their case (as
      `kobo-edits`: Kobo-derived fields only, a note naming what changed); case status back
      to Kobo's validation status (`[kobo_status]`); the assistant's case tools
      (`cases_mcp.py`: find, get, summary, add note; read-only user, no contact details,
      token, network only OpenCode joins); `ESPO_LANGUAGE` with labels from the form's
      translation. e2e 60/60 on the rig; MCP check 8/8 with the official client; Enketo:
      the follow-up form's case list (choice_filter) and prefill (pulldata) work. Found:
      EspoCRM's field-level "no edit" applies to creating too (hence a separate edits user),
      and OpenCode never retried kobo-mcp after a cold start (it now waits for its healthcheck).
      User docs: `site/cases.html`.

### 3e. W12: a box non-technical teams can run (started 2026-10-30)
`remote/box/` ([README](remote/box/README.md), PLAN 3k). Tested on the CPU rig.
- [x] **Fixed internal address:** `box.sh ip up` puts `10.254.254.254` on a dummy interface
      (`kobobox0`, a systemd unit before Docker); `BOX_IP=10.254.254.254 kobo-setup.py
      --reconfigure` binds Kobo to it. Before: the restored rig's Kobo still mapped
      `kf.kobo.local` to an old droplet's IP inside its containers (KPI → kf: connection
      refused). After: 200, and after a reboot all 21 containers came back with no `run.py`;
      `e2e-nlp.py` PASS and `e2e-espo.py --edge` 27/27 on the new address.
- [x] **`detect-tier.py`:** 8 cores, 31 GB, no GPU → CPU tier with Whisper turbo and a 23 GB
      cap, as measured in README; `./ai.sh up auto` uses it. NVIDIA/AMD branches not run yet
      (AMD falls back to the CPU until there's a Vulkan/ROCm profile, W5).
- [x] **`backup.sh`** (restic 0.16): a loop device formatted exFAT with the label
      `KOBOBACKUP` triggers the udev rule → mount, dumps (pg_dump of `kobocat`/`koboform`,
      mongodump, EspoCRM's dump and files), media, `.run.conf` + `kobo-env`, check of 5% of
      the data, unmount, status JSON. 7 s for the rig's data; the repository is 40 MB.
      A drive it can't mount is recorded as a failure too.
- [x] **Same-box restore:** deleted two projects through the API (the 63-submission W4
      survey, and the media project), then `backup.sh restore /media/kobobackup`: safety
      backup first, Kobo's front end stopped, databases and media restored, 47 s. Both
      projects back with their counts, the audio attachment byte-identical (sha256), EspoCRM
      cases back, `e2e-nlp.py` PASS, `e2e-espo.py --edge` 27/27.
- [x] **Replacement-box restore:** a fresh CPU droplet with stock Kobo 2.026.37c (same
      kobo-install commit), installed with `BOX_IP` from the start; the rig's repository
      copied over as if on the stick; `backup.sh restore`, typing the old passphrase at the
      prompt. 109 s. With the old box's superuser password (merged in), all three projects
      with their counts (63, 13, 1), the audio byte-identical, a validation-status write 200,
      KoboCAT's Digest auth 200, Enketo 200, and a new user's form deployed and a KoboCollect-
      style OpenRosa submission stored (201). Droplet deleted afterwards.
      Fixed on the way: the restored `.run.conf` carried the rig's
      `use_frontend_custom_yml` (KPI backport), which a fresh box doesn't have, so restore now
      merges only accounts and secrets into the new box's own settings; and mongorestore of
      `admin.system.users` dropped its own login mid-restore, so users are skipped and the
      restored passwords set with `changeUserPassword`.
- [x] **Offline:** with `offline.sh on`, a drive backup and the nightly unit both succeed.
- [x] **Status page** (2026-11-02): `box/status.py` writes `kobo.local/status/` (and
      `status.json`) every minute from `kobo-box-status.timer`, and when a backup starts or
      ends. On the rig: blue "starting" for the first 15 min after boot, then all green; a
      drive backup showed "don't unplug" within ~2 s and "you can unplug" when done. Stopping
      Enketo → amber (web forms only); Postgres → red; the language model → red, "data
      collection is not affected"; the assistant red on the CPU rig (no `agent-llm` there,
      which is true). `e2e-nlp.py` PASS and `e2e-espo.py --edge` 27/27 afterwards.
- Found while testing the status page, all fixed:
  - **A drive that's too small hung the backup**: restic retries writes on a full disk, so
    the page said "backing up" for minutes. `backup.sh` now does a `--dry-run` first and fails
    at once if the new data won't fit ("this backup adds about 45 MB and 4 MB is free. Use
    a bigger drive"). Failures now record their reason, not "failed (exit 1)".
  - **A stopped backup left no record** and kept the unencrypted dumps until the next run
    (bash skips the EXIT trap on a signal): TERM/INT are trapped now, and the drive unit
    unmounts the drive on stop (`ExecStopPost`).
  - **The edge never saw a new `edge.conf`**: a single-file bind mount keeps the old inode
    when the file is replaced. The compose file mounts `nginx/` now, and `library.sh up`
    reloads nginx.
  - KPI's `/service_health/` returns 500 when only Enketo is down; the page reads its lines
    and judges KPI on the rest.
- [x] **Content pack + offline install** (2026-11-02, `box/pack.sh`, `box/install.sh`; layout
      and details in `remote/box/README.md`). Built on the rig onto a DigitalOcean volume
      standing in for the USB stick: 30 GB (212 debs, 14 images at 4.9 GB, 21 GB of models,
      5.7 GB of library), 8 min, 3.5 min to rebuild. The volume then moved to a fresh Ubuntu
      24.04 droplet with outbound traffic blocked before anything was copied:
      `install.sh --pack` in 14 min (checking 14,383 files 2.5, debs 1, images 4, files 2,
      Kobo's first start 4.5) → status all green, `e2e-nlp.py` PASS (qual, translation,
      transcription at WER 0%), a `KOBOBACKUP` drive backup with the pack's restic.
      Found, and fixed: **KPI never starts on a box installed offline** (its entrypoint's
      `uv pip sync` against PyPI on every new container; `kobo-setup.py` now mounts the image's
      own requirements.txt as the "already synced" marker, and writes the backport's compose
      file instead of it being hand-placed), and a fresh Ubuntu's first-boot `apt-get update`
      hanging offline with apt's lock (the pack's apt has its own lists; daily apt timers off).
- [x] **First power-on** (2026-11-02, `box/firstboot.sh`, `box/card.py`): `install.sh` stops at
      the factory step; the first boot names the box, sets up Kobo (its passwords), the backup
      passphrase and Wi-Fi details, the AI and the label card, step by step on the status
      page. On a fresh offline droplet: factory install 11 min, first boot 6 min, all green,
      `e2e-nlp.py` PASS, a backup with the new passphrase; the card served on the box only
      (403 from outside); a second reboot kept the name and didn't re-run setup. Found: a
      `tr | head` random-string helper failing under `pipefail` (the page showed the failed step;
      a restart resumed after the fix).
- [x] **Case management on a new box, and on a replacement box** (2026-11-02):
      `firstboot.sh`'s `cases` step makes the Kobo account `cases-bridge` (not a superuser,
      sees only forms shared with it; `box/kobo-account.py`) and starts EspoCRM with its own
      passwords; the label card has EspoCRM's admin password and "share the form with
      `cases-bridge`". `espocrm.sh restore` from another box now gives MariaDB the backup's
      passwords and takes its secrets; `backup.sh restore` rewrites the bridge's token from the
      restored Kobo and the card. On a fresh droplet offline throughout: factory install and
      first boot 16.7 min, all green; the rig's backup (60 cases) restored in 139 s with
      nothing typed; `e2e-espo.py --edge --share-with cases-bridge` 28/28 (10 new cases
      through the bridge's own account, numbered on from 61). The `install.sh` SSH session
      that never closed (seen twice before) didn't happen this time (explained below).
- [x] **Hung model servers restart** (2026-11-02): Docker healthchecks on llama-server and
      whisper-server (and the agent model), and `box/watchdog.sh`, run before the status page
      every minute, restarts a labelled container Docker marks unhealthy (at most 3 times an
      hour). On the rig: whisper-server frozen with `kill -STOP`, marked unhealthy, restarted
      on the next run, green, and the page said when.
- [x] **Updates from a newer content pack** (2026-11-02, `box/update.sh`, `box.sh update-drive`):
      packs are signed (ed25519, `pack.sh keygen`), boxes keep the key from their factory
      install, and plugging a `KOBOPACK` stick into a box in use updates it if the signature
      checks out. A 37c box (form, 13 submissions, 10 cases) took a 37d pack by itself,
      offline: 4 min, Kobo down ~80 s, data there, all green, `e2e-nlp.py` PASS. Three
      tampered sticks refused. Found: a git tag clash between packs (fixed); the backport
      mounts KPI's whole `base.py`, so a 37c copy on 37d would have undone 37d's SVG-upload
      security fix: the backport now records its KPI image (`KPI_IMAGE`), `pack.sh`,
      `update.sh` and `kobo-setup.py` refuse a mismatch, and `kpi-backport-rebase.sh` moves it
      to a new release by three-way merge. The rig is on 2.026.37d now. And the SSH session
      that never closed after `install.sh`: DigitalOcean's firewall dropping a quiet
      connection on an offline droplet, not the script (README: `ServerAliveInterval`).
- Not covered yet: OpenCode sessions,
  NVIDIA/AMD tier detection on real hardware, the passphrase prompt from a real console.
- Found: DigitalOcean's kernel has no exFAT module (`linux-modules-extra` adds it; Ubuntu's
  generic kernel on a real box has it). `provision.sh` copied `*.local.env` (laptop-only
  overrides) to the droplet: excluded now. The first backup passphrase on the rig was logged
  to the journal before that was fixed: test data only, but make a new one before real use.

### 4. GPU tiers (W1) ✅ run on an H100, 2026-10-29
RTX 4000/6000 Ada and L40S stayed out of stock, so `remote/gpu-tiers.sh` ran on
`gpu-h100x1-80gb` (`NAME=kobo-box-gpu SSH_PORT=443 ./provision.sh`; deleted afterwards,
no snapshot; ~1.5 h, ~$7). VRAM is what each tier needs; speeds are a best case.
Details in [NOTES](remote/results/NOTES.md).
- [x] E4B + whisper turbo: 6.3 GB → fits an 8 GB laptop GPU
- [x] 26B-A4B on the GPU: 17.5 GB → a 20 GB card; 12 layers offloaded: 8.6 GB, just over
      8 GB (use fewer layers, or whisper on the CPU)
- [x] gpt-oss-120b: 62.8 GB → 80 GB card or a 128 GB unified-memory box (Strix Halo)
- [x] All four: qual 3/3, whisper 2% WER, translation chrF ~57–59. Bigger models gain
      nothing on these short tasks; their case is agents (W4).
- [ ] Re-run on a real laptop-class GPU (or the W5 dev unit) for representative speeds
- Lessons: the NVIDIA AI/ML image has docker.io without Compose, and first-boot apt holds
  the lock (bootstrap now waits and installs `docker-compose-v2`). Some networks block
  outgoing port 22: `SSH_PORT=443`.

## Open decisions

- **Pilot languages** (3–6). Each one becomes an `eval/fleurs-<config>.tsv` manifest.
- **Mock interviews:** ask the pilot partner for 5–10 per language, recorded on field phones
  through a Kobo audio question. FLEURS is clean read speech, so it only gives a best case.
- **KPI team:** involve them now or after a working prototype (the aim is to merge upstream).
- **kobo-mcp repo location.**
