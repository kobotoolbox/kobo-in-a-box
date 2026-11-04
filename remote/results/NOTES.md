# Run notes

The JSON doesn't record every setting, so this maps each run to its configuration.

## 2026-10-28: `s-8vcpu-32gb-amd`, CPU only (`ai.sh up cpu`, 8 threads), Gemma 4 E4B Q4_0 + mmproj

GPU droplets (RTX 4000/6000 Ada, L40S) were out of stock in every region.

| Run | Egress | Thinking | Whisper | Notes |
|---|---|---|---|---|
| 102555 | online | on (default) | large-v3-turbo q8_0 | 3/3 qual correct, 13–48 s each |
| 102948 | offline | on | large-v3-turbo q8_0 | same as above, no Kobo yet |
| 105419 | online | `--reasoning-budget 0` | large-v3-turbo q8_0 | reasoning leaks into content: 3/3 PARSE FAIL. Kobo installed |
| 105641 | offline | `--reasoning-budget 0` | large-v3-turbo q8_0 | same failure |
| 105833 | offline | `enable_thinking=false` | large-v3-turbo q8_0 | 3/3 correct, qual 6–11 s, translation ~2 s |
| 105949 | offline | `enable_thinking=false` | medium q5_0 | transcription only of interest: 19 s for 11 s clip (turbo: 23 s) |

## 2026-10-28 (later): same droplet restored from snapshot, FLEURS Spanish added

Thinking off (`enable_thinking=false`), whisper large-v3-turbo q8_0, `language=es` passed
to whisper for the 16 clips in `eval/fleurs-es_419.tsv`.

| Run | Egress | Whisper WER | Gemma audio WER | MT chrF | Pipeline chrF | Notes |
|---|---|---|---|---|---|---|
| 132810 | online | 2.0% | 2.2% | 59.4 | 57.5 | cold start: representative timings |
| 134522 | offline | 2.0% | 2.1% | 59.4 | 57.8 | LLM timings unrealistically fast: llama.cpp reused cached prompts from 132810 |

- Whisper took 13–15 s per clip regardless of length (10–27 s audio): a fixed cost per
  30 s window. Long recordings should run near 2× real time on 8 vCPU. Passing the
  language also skips auto-detect (jfk took 23 s with auto, 11 s here).
- Gemma audio (cold run) 10–26 s per clip, slower than whisper, same accuracy.
- chrF ~45–60 still means correct translations: FLEURS English is the original sentence
  the Spanish was translated *from*, so wording differs. Use chrF to compare models and
  languages, not as an absolute grade.
- Qual 3/3 correct, 6–10 s cold.

## 2026-10-29: `gpu-h100x1-80gb` (H100 80 GB, 20 vCPU), GPU tiers (`remote/gpu-tiers.sh`)

RTX 4000/6000 Ada and L40S were out of stock, so the tier recipes ran on an H100: VRAM in
use is what a smaller GPU would need, but **speeds are a best case**, far faster than a
laptop GPU. Thinking off, whisper large-v3-turbo on the GPU, FLEURS Spanish + jfk, cold.

| Run | Model | VRAM (with whisper) | Fits | Whisper | MT / call | Qual / call | Scores (WER, MT/pipeline chrF) | GPU energy |
|---|---|---|---|---|---|---|---|---|
| 091107 `e4b` | Gemma 4 E4B + mmproj | 6.3 GB | 8 GB laptop | 109× real time | 0.18 s | 0.09 s, 3/3 | 2.0% (Gemma audio 2.2%), 59.0 / 57.7 | 156 W avg, 2.6 Wh |
| 091253 `26b` | Gemma 4 26B-A4B, all on GPU | 17.5 GB | 20 GB card | 105× | 0.21 s | 0.15 s, 3/3 | 2.0%, 58.4 / 57.7 | 153 W, 2.0 Wh |
| 091526 `26b-ngl12` | 26B-A4B, 12 layers on GPU | 8.6 GB | **not quite 8 GB** | 108× | 1.57 s | 1.16 s, 3/3 | 2.0%, 58.2 / 57.5 | 138 W, 3.6 Wh |
| 091730 `gptoss` | gpt-oss-120b MXFP4 | 62.8 GB | 80 GB card (or 128 GB unified memory) | 108× | 0.92 s | 0.80 s, 3/3 | 2.0%, 57.4 / 57.1 | 245 W, 5.1 Wh |

- All four answer KPI's qual prompts 3/3 with the strict parser; translation quality is
  the same within noise. On these short tasks the bigger models buy nothing.
- 26B on an 8 GB GPU needs fewer than 12 offloaded layers, or whisper on the CPU: 8.6 GB
  includes ~1.5 GB of whisper turbo.
- gpt-oss-120b reasons before answering (its reasoning goes to `reasoning_content`, so
  KPI's parser still sees a clean answer); still under a second per call here.
- Energy figures are GPU-only for the whole smoke test (60–95 s). Add the rest of the system.

## 2026-10-29: W4 agents, OpenCode 1.19.5 + kobo-mcp (W3 settings) on the box's Kobo

CPU rig (Kobo, kobo-mcp `TOOL_PROFILES=analysis,forms,data`, OpenCode) + an H100 serving only
the agent model over the private network; 64k context, 1 slot, thinking off. 30 tasks from
`agents/w4-tasks.json` on `agents/w4-fixture.py`'s seeded survey (re-seeded before each run).
H100 speeds: a best case.

| Run | Passed | Discovery | Counts | Breakdowns | Data quality | Reading | Exports | Reports | Forms | Writes | Safety | Median / max time |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `w4-gemma-4-26b-a4b-*` | **22/30** | 3/3 | 2/4 | 7/7 | 2/4 | 1/2 | 1/1 | 2/2 | 1/2 | **0/2** | 3/3 | 5 s / 447 s |
| `w4-gpt-oss-120b-2*` | **24/30** | 3/3 | 2/4 | 6/7 | 3/4 | 1/2 | 1/1 | 1/2 | 2/2 | **2/2** | 3/3 | 7 s / 34 s |
| `w4-gpt-oss-120b-offline-*` | 8/8 | egress blocked except the VPC (model); OpenCode restarted offline | | | | | | | | 1/1 | 1/1 | 5 s / 34 s |

- **Safety held for both:** no delete tool was ever called (they're hidden and denied), the
  project and every submission survived "delete" requests, nothing went to another server.
- **Gemma 26B-A4B:** counts from paged raw submissions instead of the stats tools (47 of 63
  counted, wrong per-group numbers), 5 empty answers (the turn ends after a tool call), and
  on "put the duplicates on hold" a 211-call loop (205 `set_validation_status`, 2
  unrequested `edit_submissions`) that left nothing on hold. Not usable for writes.
- **gpt-oss-120b:** all writes and form edits right, no empty answers. Its misses: took
  `_submitted_by` (the Kobo account) for the form's Enumerator question; answered the
  submission date when asked for the interview date; asked which project instead of
  looking it up once; searched OpenCode's (empty) workspace with glob/grep instead of Kobo;
  one count off by two.
- **Prompt size drives speed:** OpenCode's first request is ~21k tokens (its prompt and tools
  + 32 kobo-mcp tools), resent every step: a task used a median of ~77–87k prompt tokens.
  On a field box, prompt processing and prompt caching set the pace, not generation.
- **Offline:** 8/8 with no internet; OpenCode and kobo-mcp logged no failed outbound
  attempts. The host's resolver did see DNS queries fail as the firewall closed (process not
  identified): a per-process DNS capture is the stricter test still to do.

Found while building it (fixed in agents/):
- `opencode run --format json` (1.19.5) can exit before printing the last step's text and
  `step_finish`; the runner reads the stored session with `opencode export` instead.
- Gemma 4 with thinking on ends turns after thinking with no answer: `AGENT_THINKING=false`.
- OpenCode reads its config only at start: `agents.sh up` recreates the container.
- 1.19.5 bundles `@ai-sdk/openai-compatible`, so the box provider loads offline; OpenCode's
  `dev` branch has reorganised providers, so recheck offline when bumping the version.
- New projects require auth for OpenRosa submissions: the seeder sends the token.

Bring-up runs from before these fixes, kept for the record, not results:
`w4-pipeline-check-*` (0/1, timed out at 400 s), `w4-smoke-gemma-*` (0/2 three times, at
300 s then ~40 s, then 2/2 in 2.5 s once fixed) and `w4-smoke-gptoss-*` (1/1).

## 2026-10-30: W11 case management, CPU rig (`s-8vcpu-32gb-amd`)

`espocrm/e2e-espo.py --edge` (health referral scenario, real Kobo through the edge),
`w11-e2e-*.json` (pulled from the rig by `park.sh`).

| Run | Egress | Result | Notes |
|---|---|---|---|
| 111817 | online | 27/27 | 9 cases after 16 s, the later visit after 27 s |
| 112125 | offline | 27/27 | after `espocrm.sh down` + `up` with outbound blocked (cold start) |
| 112351 | offline | 27/27 | with a packet capture on the stack's Docker network: 0 outbound packets over the run and ~2 min of EspoCRM's scheduler; a control connection to 1.1.1.1 was captured |

## 2026-11-04: kobo-transfer sync, field kits → hub, three CPU rigs (`s-8vcpu-32gb-amd`)

`site-a`, `site-b` and `hub`, all restored from `kobo-box-ai-snapshot` (Kobo 2.026.37d + the
backport), on one DO VPC. kobo-transfer at `1ae7a04` (2026-07-06) on each kit, pushing to
one hub project with `sync/push.sh` (`--sync --validation-statuses --analysis-data`);
`sync/e2e-sync.py check` from each kit against the hub. The `sync-*.json` files stayed on the
kit droplets (copying them off was blocked).

| Step | Egress | Submissions, attachments, validation statuses | AI results |
|---|---|---|---|
| site-a: 5 (AI on 1: transcript, translation, qual, 69 s on CPU) | online | 5/5, byte for byte | **not copied** |
| site-b: 4 | online | 4/4 | none to copy |
| site-a re-run, nothing new | online | "in-sync", nothing sent | |
| site-a: 2 more, 1 synced status changed | online | only the 2 sent; the status change followed | **not copied** |
| site-b: 3 more | offline (VPC only) | only the 3 sent | none to copy |

Hub at the end: 14 rows, 14 unique uuids (7 per site), 2 attachments each (28 in the
database, so `--sync` sent no media twice), one `__version__` (the hub form's).

Found:
- **Analysis data doesn't sync.** kobo-transfer posts to `advanced_submission_post/<uid>`
  (404 on this KPI) and copies the old `advanced_features` format; KPI now keeps them in
  `/api/v2/assets/<uid>/advanced-features/` and `/data/<uuid>/supplement/` (`_version
  20250820`). The run prints "Something went wrong with <uuid>" and still ends "✨ Done".
- Its "Creating analysis form in dest project" step PATCHes the hub's `advanced_features`
  with each kit's own, so with several kits the last one to sync would win once it works.
- `_supplementalDetails` in the data list shows transcripts and translations as `""` until
  a person reviews them; checks have to read `/supplement/`.
- Every box is `kf.kobo.local`, so a kit can't reach the hub by name. The rig used a port
  forward (`kf.kobo.local:8090`); it works because kobo-transfer only follows the hub's
  `next` links past 1000 submissions. The host itself doesn't resolve `*.kobo.local` either
  (only the containers do) until the hotspot's dnsmasq: `/etc/hosts` on the rigs.
- Site comes from a `site` question in the form; nothing marks a kit's submissions by itself.
- Not tested: hub → a cloud server (needs an account), and the push the other way (the hub
  pulling from kits would break attachments: their download URLs carry the kit's own name).

### Same day, after the fixes (same three rigs, offline but for the VPC)

kobo-transfer branch `supplement-api` (`~/code/kobo-transfer`) and KPI's supplement import
(`local-nlp-backend`, in the backport; the hub restarted with it by `kobo-setup.py
--reconfigure`, offline). The check now also compares each kit's whole supplement with the
hub's (every version, uuid, date and review state).

| Step | Result |
|---|---|
| site-a → hub, no new submissions (the first fix to `run.py`: it used to stop at "in-sync") | 5 AI versions imported, still pending review; whole supplement identical |
| `review` on site-a (accept transcript and translation, verify the qual answer), sync again | 3 updated; identical again (first try missed `_dateVerified`: fixed) |
| re-run, nothing changed | 0 added, 0 updated |
| site-b: 1 more with AI and its own qual question, sync | 5 versions imported; the hub has both sites' qual questions, neither hidden; both kits' checks pass |
| site-a (reviewed) → site-b's form, stock KPI routes (no import: like KoboToolbox's servers today) | the 3 reviewed results as manual entries; re-run adds nothing |
| site-b (unreviewed) → site-a's form, stock routes | nothing copied, "3 unreviewed left at src" reported |

A failure now prints `❌ <uuid> (Analysis data): <status> <body>` and the run exits 1.

KPI tests (`kpi-test.sh kobo/apps/subsequences/`, hub online for pip only): 433 and 422
passed, but 1 of the 10 new import tests failed: a `complete` transcript with no value was
imported. KPI's own `validate_submission_supplement()` checks nothing below the question
(each question's schema is a dict of action schemas, not a schema), so it accepts any
action data; real writes are safe because each action calls `validate_result()`. The import
now does too: 10/10 in both settings. Last run with it, offline: one more AI submission on
site-a imported exactly, site-b in-sync; hub at the end 16 rows, 16 uuids, 8 per site, 32
attachments. (site-a's check then differs on one submission whose results went to site-b
as manual entries during the stock-route test and came back: the hub holds the union of
both copies, which is right; kits syncing into each other isn't a real flow.)
Still open: hub → a KoboToolbox server (an account), proposing both changes upstream, how
kits and the hub address each other (all `kf.kobo.local`), and a site id kits stamp on
their own submissions.

## 2026-11-04 (later): syncing built into the box, on kits installed from a pack

The rig (`kobo-box-ai`, restored) built a pack with the sync pieces (`box/sync.py`, the
edge's per-box names, the `sync` account in first boot, kobo-transfer `supplement-api` in
`kobo-transfer/`, the KPI import in the backport); three fresh Ubuntu 24.04 droplets
(`s-8vcpu-32gb-amd`), offline from the start but for the VPC, took it with
`install.sh --pack … --first-boot-now`: 11–15 min each, all green but "no backup to a drive
yet". Names: hub `kobo-frmw`, site-a `kobo-chxq`, site-b `kobo-29p4`. Each with an `e2e`
account (`kobo-account.py`, not a superuser) owning the test form; the form shared with
`sync` (kit: view submissions; hub: view, add, change, validate submissions). Each kit paired
once with `ssh <hub> cat /etc/kobo-box/sync.token | sync.py hub 10.110.0.9 -` (the key went
hub → kit over the VPC, not through the laptop). After that only the timer ran syncs, except
where noted. Checks: `e2e-sync.py check` on each kit against `kf.kobo-frmw.local`, with the
hub key the kit holds (fresh boxes don't share tokens).

| Step | Result |
|---|---|
| First timer run after pairing (12:00) | site-a 5 sent + 5 AI versions in 7 s, site-b 4 in 6 s; both checks PASS (now also comparing answers); status rows "Synced to the hub kobo-frmw just now" |
| Edits: site-a edits 2 (one with AI results, one twice), the hub edits a site-b submission, both edit one of site-a's | site-a: 2 sent as edits, 1 conflict; site-b: 1 kept at the hub. Hub: 9 rows for 9 roots, edited answers and attachments there, AI versions unchanged; the hub's correction and its side of the conflict untouched; checks PASS but for the two expected to differ |
| 1,100 more on the hub (third site, no media), then 2 new + 1 edit on site-b | sent in 5 s; hub 1,111 rows over 2 pages, 1,111 roots: the second page of the hub's list was followed through `kf.kobo-frmw.local` |
| site-a cut off from the hub (iptables); the hub's `sync` loses add_submissions, site-b adds one | site-a: "Last synced … The hub isn't connected now" (green); site-b: "1 submission … couldn't be sent: the hub's sync account isn't allowed to add them: … share … with …" (amber, from the 403). Both fixed: the next timer run sent the waiting submission, all green |
| `sync.py resolve <uuid> --keep here` (site-a) and `--keep hub` (site-b, after a fresh conflict) | here: sent as an edit straight away, check PASS with nothing skipped; hub: left as it was, conflict gone, green |
| site-b: backup (no media), pairing and the hub's hosts entry removed, restore | 57 s; "paired with the backup's hub"; the next sync put the hub's name back in /etc/hosts and sent a new submission; check PASS |

Found and fixed on the way:
- The edge's `proxy_redirect` with numbered captures failed every `kc.kobo.local/` request
  ("no buffer space in script copy": the map's regex reset `$1`): named captures.
- `sync.py` built the kit's own address as `kf.kobo.local.local`. The pack carries that
  bug; the kits were fixed by hand and the code is right now.
- Resolving a conflict had no way out ("edit one to match" leaves it a conflict forever):
  `sync.py resolve`.
- The status row counted edits as new submissions, and didn't say which conflicted:
  kobo-transfer's summary now has `edits_sent` and `conflict_uuids`.
- `kobo-transfer` stopped without a summary on a 403 from validation statuses or analysis
  features: it now writes one with the error.

Not tested: `update.sh` giving an older box its `sync` account; pairing over a bare cable
(no DHCP: mDNS or link-local, W5 box); syncing to a KoboToolbox server online.

### Same day, last: kobo-transfer PR #60 on two rigs

kobo-transfer `supplement-api` at `4e024cf` (with the host-aware URL rule; PR
kobotoolbox/kobo-transfer#60) on the rig (`kobo-box-ai`, as a field kit) and a hub restored
from the same snapshot (`kobo-box-hub`); each given its own `sync` account
(`kobo-account.py`), its names (`box.sh ip up`, `render.py`), offline but for the VPC. The
hub's key went hub → kit over SSH on the VPC. The hub held 1,100 other submissions (two
pages of its list), the kit 4 with photo and audio, AI on one.
- Pairing started a sync: 4 sent, 5 AI versions, 6 s; check PASS (answers, attachments,
  statuses, AI versions as they are).
- Next timer run (13:45): 1 new submission and the AI one edited went across, 1 + 1 edit;
  check PASS; status "Synced to the hub kobo-box-hub just now: 1 new submission and 1 edit".
The rig was unpaired (`sync.py hub --forget`) and parked with this kobo-transfer and its
`sync` account; the hub deleted. `park.sh` brought this run's files back:
`sync-check-20261104-134037.json` (the pairing sync), `-134517.json` (the timer sync) and
the kit's `sync-manifest-A.json`.
