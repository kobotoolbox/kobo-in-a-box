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

## 2026-11-05: paper forms on a box installed from a pack (W13)

The rig (`kobo-box-ai`, restored) had no kff image: W13 was built on a second rig, so the
packs since had no paper forms. `paper.sh build` from kff `66d4c97` (only `.git` copied),
`paper.sh up`, `pack.sh build` (31 GB, `kobo-field-forms:66d4c97` in `images/IMAGES`). A
fresh Ubuntu 24.04 droplet, offline from the start but for the VPC, took it with
`install.sh --pack … --first-boot-now` (name `kobo-9bxp`).

- First boot's `paper` step: `paper-forms` account and owner-only token, kff up and
  healthy, landing page link, card section, status "Paper forms: Working".
- Access: the edge returns 401 without the password or with a wrong one, 200 with it.
  `POST /fetch` of a form not shared with `paper-forms`: "Not found … check that you can
  see it"; shared with View form + Add submissions (as Kobo's sharing dialog does): fetched.
  (Shared through the API with `add_submissions` only, KPI doesn't add `view_asset`: the
  form stays invisible. The dialog always includes it.)
- `paper.sh e2e --sheets 2`, offline, as `paper-forms`: first **failed**, "The vision model
  returned HTTP 500" (llama-server: "image input is not supported … provide the mmproj").
  `detect-tier.py` wrote `LLM_MMPROJ=` for every tier, so first boot started the batch
  model without its vision projector; the status page still said "Working". Fixed: the
  projector whenever its file is on the box, and the status page reads `/props` and goes
  amber when vision is off. After `detect-tier.py` + `ai.sh up auto`: **e2e passed** in
  266 s: read 92.9 / 95.2 / 97.6 / 97.6% of 42 fields in the four profiles, wrong and
  unflagged 0.0%, resubmission a 202 duplicate.
- `/root/paper.secrets` was 644 (`paper.sh`'s umask didn't reach the redirect): fixed, 600.
- Backup: a file-backed drive labelled `KOBOBACKUP`, attached with `losetup`, started the
  drive backup by itself. exFAT **failed** ("couldn't be opened"): DigitalOcean's kernel has
  no exfat module (no linux-modules-extra). The same drive as ext4: full backup in under a
  minute, drive unmounted, "You can unplug the drive". Real boxes on Ubuntu's generic
  kernel have exfat; the autoinstall (W12) must keep it.
- Restore: paper forms stopped, their store wiped and started empty (the fetched form
  gone), `backup.sh restore /media/kobobackup`: 70 s, the form back, the token refreshed,
  the secrets still 600. Case management went amber for ~2 min (the bridge got 502s while
  KPI restarted), then green by itself.

Not run: a restore onto a **replacement** box, and `update.sh` bringing the kff image.

## 2026-11-05: OpenCode's permission rules on the Kobo tools (PRODUCT-247)

W4's runner used `opencode run --auto`, which approves every "ask", so it never checked
that writes wait for a person. `agents/w4-permissions.py` on the CPU rig: OpenCode 1.19.5
(`opencode serve`) on a stand-in model (an OpenAI-compatible server in the script) that
asks for exactly the tool under test, with the box's real `opencode.json`; the script
watches `GET /permission`, replies through `POST /permission/<id>/reply`, and reads each
call's outcome from the session (after a rejection OpenCode ends the turn, so the model
never sees it). Placeholder arguments name no real project, so nothing could change even
if a call ran.

First run, two config bugs:
- **Case notes added without asking.** OpenCode names MCP tools `<server>_<tool>`: the note
  tool is `cases_cases_add_note`, so `"cases_add_note": "ask"` matched nothing and
  `"cases_*": "allow"` let it run. Rule now `cases_*add_note`.
- **`kobo_delete_dashboard` offered.** The `tools` map (`false`) doesn't hide MCP tools in
  1.19.5; submission and project deletes were absent only because kobo-mcp's profile leaves
  them out, the dashboards profile has the dashboard delete. Now `"kobo_delete_*": "deny"`:
  OpenCode then doesn't offer it at all. The `tools` map is gone.

Runs: `-085620.json` (before the fixes: the dashboard delete offered, and the approval
check's own bug, no `submission_ids`), `-085925.json` (fixed; only the drift check too
strict about a denied delete), `-090019.json` (final).

Final run (`w4-permissions-20261105-090019.json`, PASS): 57 Kobo tools and 4 case tools
offered; every one of the 27 that change data asked first and was refused after "reject"
(add_dashboard_source, add_dashboard_table, add_transcript, archive_evidence,
archive_project, clone_project, create_dashboard, create_export, create_submissions,
deploy_form, duplicate_submission, edit_submissions, fetch_dashboard_boundaries,
generate_dashboard_layout, publish_narrative, put_dashboard_table, refresh_dashboard,
remove_dashboard_source, revert_dashboard, save_evidence, set_dashboard_settings,
set_table_columns, set_validation_status, update_dashboard, upload_form_media,
withdraw_narrative, cases_cases_add_note); reads (whoami, list_projects) ran without
asking; no delete tool offered; `opencode.json`'s read-only list matches kobo-mcp's
`readOnlyHint`; `set_validation_status` on a real submission: rejected, unchanged; approved
once, approved → on hold (set back afterwards). Not done: the same with a real agent model
(the CPU rig's batch model has a 16k context, OpenCode's prompt with the tools is ~21k): on
the GPU rig.

## 2026-11-05: updating a box from an older pack; the knowledge base (W10) started

The rig (`kobo-box-ai`, restored) built two packs: one from the code at `4445ebf`
(3 November, before W9, W13 and W14: first boot had no dash, paper or sync step) and one
from today's (`20261105-0946`). Fresh Ubuntu 24.04 droplets, offline but for the VPC.

- **Old box** (`kobo-9dkr`, from the old pack, first boot done): a form and 5 submissions
  (`e2e-sync.py seed --site A`), then `update.sh --pack` with today's pack over SSH: 3½ min,
  exit 0. Catch-up (`firstboot.sh catch-up`, new) set up dashboards, paper forms (the
  `paper-forms` account, `/root/paper.secrets` 600, the card's section) and the `sync`
  account (token 600), and wrote the card again; `e2e-sync.py check` PASS on the 5
  submissions. Images: "0 loaded, 17 already here" and Kobo "unchanged": the old pack was
  built on today's rig, so it carried today's images and KPI backport.
- **Failed:** `status.py` didn't parse (a quote in the new "setting up what this kit didn't
  have yet" label), so the status page stayed on "Updating this kit. Leave it switched on."
  Fixed; `pack.sh build` now checks every script parses first (it stopped on this one).
- **Replacement box** from today's pack: the factory install **failed** at "library and
  status page", the same bug. Droplet deleted; a fixed pack is building.
- The old box's backup to a file-backed ext4 `KOBOBACKUP` drive: full, with EspoCRM,
  dashboards and paper forms (the test form fetched into kff first), drive unmounted after.
  For the restore onto the replacement box.

Knowledge base: `knowledge.sh build` (image, bge-m3 Q8_0 0.6 GB), `index` of the Kobo guide
(the library's HTML, en/es/fr, ~470 pages): ~8 s a page on the 8-vCPU rig (~1 section/s
with 8 threads, while packs were building), so about an hour. Eval to follow.

Later the same day, with the fixed pack (`20261105-1007`, built without the half-made index):

- **Replacement box** (`kobo-6tmb`, a new droplet, offline but for the VPC): factory
  install + first boot 13 min, all green. The old box's drive image moved to it over the
  VPC (as a drive would be carried), and its passphrase from the old box (as off its card):
  plugging the drive in backed up the new box first (its own repository on the same
  drive), then `backup.sh restore /media/kobobackup/kobo-box-kobo-9dkr` with
  `PASS_FILE`: 2 min 19 s. The 5 submissions checked out, the paper-forms form fetched on
  the old box was in kff (signing in with the new box's own password, still 600),
  dashboards and case management back, the status page "Everything is working".
- **Pairing after the update:** the updated old box (as a field kit) paired with the new
  one (as its hub) with its catch-up `sync` account: `sync.py hub 10.110.0.4 -` with the
  hub's key read over the VPC; 2 new submissions seeded, one sync, `e2e-sync.py check`
  against the hub: 7 of 7, PASS.

The knowledge base, once indexed (426 pages, 2,696 sections, 52 min, 12.8 MB):

- `knowledge.sh eval` (33 answerable questions, 11 with no answer), three rounds:
  `knowledge-eval-1.json` first (hybrid hit@1 0.58, hit@8 0.88; the first result in the
  question's language for half the es/fr questions); `-2` with the question's language
  first (English for others) and two sections a page at most (same language 1.0; meaning
  hit@1 0.55 → 0.61); then common words out of the word search and the word ranking at
  half weight (0.25 / 0.5 / 1 compared): hybrid hit@3 0.79, hit@8 0.94 (meaning alone
  0.76, 0.88). No similarity line separates the unanswerable questions (max 0.77 against
  an answerable minimum of 0.52).
- MCP through the edge: three read-only tools; a wrong Host header gets 421.
- OpenCode: the first permissions run offered no knowledge tools: `agents.sh` writes
  OpenCode's `mcp` section itself, so the entry in `opencode.json` was dropped. Now
  `agents.sh` adds it when the knowledge base answers. `w4-permissions.py` (now with the
  knowledge tools): offered, run without asking, search returns `http://kobo.local/docs/`
  URLs; PASS throughout (`w4-permissions-20261105-105628.json`).
- A pack with it (`20261105-1058`: the image and `knowledge/`), and the old box updated
  again from `-0946`: 3 min 22 s, catch-up added the knowledge base, the status page fixed
  and all green ("Documentation search: Working", the sync row "Synced to the hub kobo-6tmb
  3 minutes ago"), `knowledge.sh search` on the box answered from its own index.

## 2026-11-05 (evening): the knowledge base on the GPU rig: more docs, the reranker, answers

No `gpu-h100x1-80gb` in any region (16 tried); a `gpu-h200x1-141gb` in nyc2. The CPU
snapshot's copy to nyc2 ran over an hour without finishing, so the CPU rig was restored in
ams3 and reached the GPU over the public network, the GPU firewall open on 8083 (the agent
model), 8091 and 8092 (bge-m3, the reranker, on CUDA) to the rig's address only. Only test
questions and the docs' text crossed it.

- Library: `library.sh docs-odk` (getodk/docs `1b4d4cd`, 146 pages; needed libenchant;
  analytics beacon and MathJax removed, Font Awesome vendored: `check` OK), `docs-xlsform`
  (2 pages, test rigs only).
- Index with QGIS on: 1,378 pages, 13,043 sections, 63 MB, 10 min with the GPU's embeddings.
- Retrieval (`knowledge-eval-3.json`, `-4.json`), 45 questions: hybrid hit@3 0.73, hit@8
  0.89; with the reranker (its order of the first 10) 0.76, 0.89, hit@1 0.49 → 0.53.
  Settings compared: its order or fused with hybrid's, 10/20/40 candidates: within one
  case of each other. Reranking 10 sections: ~105 ms on the H200, 14–19 s on the rig's CPU.
- Answers (`knowledge-answers-gpt-oss-120b-20261105-144812.json`, rescored): the first
  smoke run, with only the MCP server's instructions, answered the Spanish 2FA question
  from memory and called `kobo_refresh_dashboard` (a write: OpenCode waited for an OK the
  script never gave, so `answers.py` now rejects and records any). With
  `agents/knowledge-instructions.md` and a reminder after the results: 32/56 pass;
  searched 47; made-up URLs in 2; an expected page cited 28/49; nothing it asked to change.
  The full list of failures is in the report; the guide (`site/knowledge.html`) and
  `knowledge/README.md` summarise them.
- Screenshots (`site/knowledge-shots.py`, Playwright on the rig, OpenCode's password kept
  there): four sessions in OpenCode's web interface, the cited Spanish guide page at its
  section, the ODK guide in the library; `site/static/knowledge/`.

## 2026-11-05 (late): web sign-in offline for users with unverified emails

Found 2026-10-30: KPI's default `ACCOUNT_EMAIL_VERIFICATION=mandatory` makes allauth send a
confirmation mail when such a user signs in (or signs up), and with kobo-install's SMTP
backend and no mail server the request is a 500. API tokens are unaffected, which is why the
other tests never hit it. The fix, `offline_mail()` in `kobo-setup.py` (no verification, KPI's
file mail backend, in `kobo-env/envfiles/smtp.txt`), had been on every box since but never
tested: the restored rig already had it from an earlier `--reconfigure`.

`e2e-signin.sh` (with `e2e-signin.py` in a Playwright image) on the CPU rig, `offline.sh on`
(PyPI unreachable from the rig), a new user each run, deleted afterwards:

- **Control, kobo-install's stock settings** (smtp backend, verification unset → mandatory;
  `kpi` container alone recreated): sign-up **500** at `/accounts/signup/`, sign-in **500**
  at `/accounts/login/`, not signed in either time. The bug as found.
- **With the fix** (two runs): sign-up lands signed in on `#/projects/home` (`/me/` names
  the user), no "verify your email" page; signed out; sign-in again, signed in; no 5xx
  response on any request; in the database the user's `EmailAddress` is `verified=False`;
  no file in KPI's mail folder. 9/9.

Found on the way: the Playwright image has the browsers but not the Python package, so
`pip install` at run time (as in `site/kobo-shots.py`) fails offline; the test uses a local
image with it installed (`kobo-box-test/playwright:1.55.0`, command in `e2e-signin.sh`).
And KPI's user model is `kobo_auth.User`: `django.contrib.auth.models.User` raises
"Manager isn't available" in `manage.py shell`.

## 2026-11-06: Kobo accounts and KoboCollect QR codes on the box (W15)

`box/users.py` at `kobo.local/users` on the CPU rig (restored from the 2026-11-05 snapshot,
Kobo 2.026.37d), tested with `e2e-users.sh` through the edge nginx and in a real browser
(`site/users-shots.py`, Playwright image).

- **Why accounts from KPI's registered-application endpoint needed a first web sign-in:**
  KoboCollect's Digest sign-in needs a django-digest partial digest, and
  `CreateUserSerializer.create()` calls `set_password()` before setting the username, so
  none is stored. A new user's `/formList` with Digest was 401 (three users, also 20 s
  later); after one Basic-auth API call (or `authenticate_user/`) with the password, 200.
  The website, API tokens, sharing, the verified email, the organization and KoboCAT's
  user and profile were all there before any sign-in. `users.py` calls `authenticate_user/`
  once per new account.
- **Also found:** the endpoint moved to `/api/v2/authorized_application/users/` (the
  Notion page's `/authorized_application/users/` is 410); a taken username is a 500
  (IntegrityError: the serializer's own `username` field drops the unique check); deleting
  a user in KPI leaves its copy in KoboCAT's database, and the same username then can't be
  made again (124 leftover test users cleaned with SQL, `kpi-delete-users.sh`); Chrome
  posts forms with `Origin: null` under `Referrer-Policy: no-referrer` (the page's origin
  check refused its own sign-in in a browser, never with curl; now `same-origin`).
- **e2e-users.sh, offline (`offline.sh on`, example.org unreachable): 24/24**
  (`w15-users-20261106-082542.txt`): admin-only sign-in (wrong password and non-superuser
  refused), form token required; one account and a CSV list ready for KoboCollect (Digest
  200) and the API at once; a list with a bad row makes nothing and names it; Excel's BOM
  and semicolons; a taken username reported, not failed; emails filled in and verified;
  QR codes read off the page with zbarimg and decoded (Base64, zlib, JSON) with the server,
  the username and a password that signs in, and the saved Collect settings (file 600);
  an older account's code has no password; deactivated → Digest 401 and API 401 with the
  project kept, reactivated → both back and the project theirs; admins can't be
  deactivated; sign-out forgets the results. Also 24/24 online.
- **Speed:** 100 accounts from a list in 143 s (two password hashes and KPI's signals per
  account, 8 vCPUs), and the first of them signed in to KoboCollect.
- **KPI fix** (branch `fix/create-user-partial-digest` from `origin/main`, not pushed):
  `set_password()` after the other fields, and a `UniqueValidator` on `username`, with two
  tests. `kpi/tests/test_authorized_application.py` with `kpi-test.sh` (`KPI_SRC=`): 10/10
  under `testing` and `testing_no_stripe`; the same tests on the unpatched serializer: 8/10
  (both new ones fail, the duplicate as a 500) (`w15-kpi-create-user-20261106.txt`).
- Not tested: scanning a code with KoboCollect on a phone; a box from a pack.

## 2026-11-06 (later): KoboCollect itself, on a stand-in phone on the droplet

- **The phone:** `phone.sh` runs redroid (Android 13, x86_64) in Docker on the droplet's own
  kernel, so no KVM (DO has no nested virtualization); `binder_linux` from Ubuntu's
  `linux-modules-extra` on 6.8.0-147. The library's KoboCollect v2025.2.3 APK, driven
  over adb with uiautomator2. Its hosts file stands in for the hotspot's DNS: `*.kobo.local`
  → `BOX_IP`, reached through the Docker bridge as a phone reaches the box's address.
  Up in about a minute; no Google Play services (Collect only logs about it).
- **e2e-collect.sh, offline (`offline.sh on`, example.org unreachable): 8/8**
  (`w15-collect-offline-20261106-100131.txt`, screenshots in `collect-20261106-100131/`):
  an account made on the accounts page and its QR code; a three-question form deployed;
  on a phone fresh from the box, Collect adds the project with the code's server,
  username and password, signs in over Digest with no web sign-in first, downloads the
  form, the answers are typed in, finalized and sent ("Successful submission"); KPI has
  them, submitted by that account. About 1 min a run; 8/8 online too. The Collect steps
  passed in all five offline runs (the first three before the cleanup fix below).
- **QR codes:** the phone has no camera, and both of Collect's QR screens (first launch,
  and Reconfigure with QR code) close when it fails, before their "Import QR code" menu
  can be reached. So the test reads the code itself (zbarimg) and types in what it holds;
  Collect's own reading of the code, and the admin settings in it, are still untested.
  The Android emulator's virtual camera can show an image (`-camera-back virtualscene`),
  but needs KVM: a GitHub Actions runner, a GCP machine with nested virtualization, or a
  phone.
- **Also found:** `kpi-delete-users.sh` couldn't remove an account with submissions from
  KoboCAT's database (`viewer_parsedinstance` points at `logger_instance`, not at
  `auth_user`), and rolled back; it now follows foreign keys all the way down. 10 leftover
  test accounts deleted with it.
- Ran on `kobo-box-collect`, restored from `kobo-box-ai-snapshot` (2026-11-06) on
  `s-8vcpu-32gb-amd`; deleted afterwards with its firewall.

## 2026-11-06: offline maps, `kobo-box-maps` (`s-8vcpu-32gb-amd`, from `kobo-box-ai-snapshot`)

Protomaps build 20261105, `pmtiles extract` with geoBoundaries ADM0 outlines, 8 download
threads, from ams3 (MAPS-PLAN phase 0):

| Area | z15 | z14 | Time (z15) |
|---|---|---|---|
| Lesotho | 149 MB | 76 MB | 9 s |
| Colombia | 585 MB | 286 MB | 32 s |
| Venezuela | 308 MB | 158 MB | 27 s |
| Colombia + Venezuela (one file) | 883 MB | | 33 s; MBTiles copy 1,074 MB, +40 s |

Tile server (tileserver-gl 5.7.0, 8 vCPU): a z15 image tile of central Bogotá in 0.11 s the
first time, under 1 ms from the edge's cache; ~205 MB of memory. `e2e-maps.py --dashboard`
offline: 27/27. From the laptop, plain http to the droplet took 59 s to connect every time
(ssh fine); screenshots and QGIS went through SSH tunnels instead.

Later the same day, the country picker (`maps/picker.py`) on a new `kobo-box-maps` from the
same snapshot, with `box.sh install`: through the page, Lesotho added in 90 s and Ecuador in
~60 s (each cuts every country on the box again from build 20261106, plus the MBTiles:
COL+LSO+VEN 1,032 MB), Lesotho taken off offline in 63 s. `e2e-maps.py --picker` 11/11,
`--picker-offline` 9/9, `e2e-maps.py` 27 checks, 0 failures.


## 2026-11-10: KPI `main` with the local backend, typed answers and photos, `kobo-box-nlp` (`s-8vcpu-32gb-amd`, from `kobo-box-ai-snapshot`)

KPI built from kpi `main` 4a345b570 + `local-nlp-backend` rebased onto it
(`local-nlp-backend-main`), in place of 2.026.37d and the backport; migrations ran on the
snapshot's data. Gemma 4 E4B Q4_0 with its Q8_0 vision projector, Whisper large-v3-turbo,
8 threads.

- **Unit tests** (`kpi-test.sh`, `kobo/apps/subsequences/`): 438 passed (`testing`), 427
  passed + 12 skipped (`testing_no_stripe`).
- **`e2e-nlp.py` offline** (egress checked blocked, LLM restarted first):
  `e2e-nlp-image-offline-20261110.txt`. PASS: text qual 3/3 (8–14 s), photo qual 3/3
  (78 s for the first question, 9–13 s for the next two), translation 24 s, transcription
  0% WER in 30 s. Online, before the branch sent the image first, the photo's 2nd and 3rd
  questions also took ~100 s and two timed out (the KPI tests were running).
- **Through the UI offline** (`site/nlp-shots.py`, a French typed answer and a photo):
  Translate & analyze from the submission's … menu; automatic English translation in 26 s
  (faithful); 4 questions on the typed answer with Generate with AI, 10–15 s each, all
  right (Broken; cost of repairs, long walk, illness; 12000; spare part and training); 3 on
  the photo, 81 s then 10 and 14 s, all right (Hand pump; animals at the water point; "a
  concrete basin with a metal pump mechanism installed in the center").
- **Image budget**, one question on the photo, idle CPU: the model's default ~990 image
  tokens 74 s; `--image-max-tokens 560` 36 s; 280, 17 s ("Concrete water trough" for the
  kind of water point, against "Hand pump station" at the default).
- Deleted afterwards with its firewall.

## 2026-11-11: the box's KPI image on the rig (`kobo-box-ai`, `s-8vcpu-32gb-amd`), CPU only

KPI `kobo-box/kpi:4a345b570-8ad95b67fc8c` (`kpi/build.sh`), the vendored kobo-espo-bridge
(e3408e4), kobo-dash `main` a2b86cd, kobo-mcp `w9-box-main`. Offline (egress checked blocked).

- **Benchmark** (`smoke-test.py`, LLM restarted first): `log-cpu-20261111.txt`,
  `20261111-083041-gemma-4-E4B-it-Q4_0.gguf.json`. Unchanged: Whisper 2.0% WER, chrF 59.4 text
  / 57.5 pipeline, translation 2.6–3.8 s. Qual on a transcript 3/3 (6–11 s); **on a typed
  answer** (French, KPI text-source prompts) 4/4 (7–11 s); **on a photo** (KPI image prompts,
  image first) 3/3: 72 s for the first question with no prompt cache (1,240 prompt tokens),
  then 8 and 11 s. GPU: none in stock in any region (all sizes polled every 5 min); not
  measured.
- **Suite** (`e2e-all.sh`): every test passes except `maps_dash` (COL/VEN ADM1 not on the
  rig, known since 11-06): nlp, signin, users, cases 27/27, ledger 38/38, edits 34/34,
  follow-up 42/42 (with `BRIDGE_LIST_MIN_SECONDS=20`), cases-mcp, dash, maps, mcp, agent
  permissions (60 kobo tools, 4 cases tools), knowledge, paper, collect.
- **EspoCRM feeds** (kobo-dash `main`, `dash/e2e-dash-espo.py`): 15/15 offline. An API user
  reading the Nutrition (OTP) team's cases and 5 fields, its key saved in kobo-dash's admin
  page with `http://cases.kobo.local`, a feed through kobo-mcp: 123 of 228 cases, no caregiver
  columns, an edit in EspoCRM read again (version 2). A field the role can't read
  (`cCaregiverPhone`) is accepted as an always-empty column instead of refused (kobo-dash
  reads EspoCRM's metadata, which lists every field). The admin page's EspoCRM address
  input is unstyled (`type=url`).
- **Pack** `20261111-0859` (35 GB, signed, `kpi_image` `kobo-box/kpi:4a345b570-8ad95b67fc8c`),
  built on a new volume in 8 min. First try stopped at its own check: the rig had empty
  `espocrm/bridge.py` and `templates/` directories, left by Docker when the old compose
  file's bind mounts lost their files during the switch to the vendored bridge.
- **Update** (`kobo-box-clean`, installed offline from the 2.026.37d pack `20261111-0655`):
  `update.sh` offline from the new pack, 7.5 min (`box-update-steps-20261111.txt`): all six
  KPI services on the box's image, `ai-setup.py` applied (`ASR_MT_INVITEE_USERNAMES='*'`, 6
  languages). Then, offline: `e2e-nlp.py` PASS (text qual 3/3, photo 3/3 with 81 s for the
  first question, translation 32 s, transcription 0% WER); `e2e-espo.py --edge
  --share-with cases-bridge` 28/28 (after `espocrm.sh up --demo-users`, which a box doesn't
  have); `e2e-dash.py` 23 ok; `e2e-dash-espo.py` PASS (10 cases of the team); knowledge,
  paper PASS. `e2e-users.sh` passed every account check up to the QR code, which needs
  `rsvg-convert` and `zbarimg` (the rig's test tools, not on a box); `e2e-signin.sh` needs
  its Playwright image (built online on the rig).
- **Found: superusers can't submit** on KPI `main` (DEV-32, `ALLOW_SUPERUSER_SUBMISSIONS`
  off by default): a superuser `e2e` got 403 "Access denied" from `/submission` after Digest
  succeeded. The box's admin collects with an account from `users.py` (box/README.md).
- **Fresh install from that pack failed** at first boot: kobo-install's start checks the
  databases with `compose -f docker-compose.frontend.yml -f …override.yml run --rm kpi`
  (`Upgrading.migrate_single_to_two_databases`), without the custom yml, so it needs
  kobo-docker's own `kobotoolbox/kpi:2.026.37d`, which wasn't packed: only images a
  container runs are, and the rig's all run the box's image now (the updated box still had
  the stock one). `pack.sh` now always packs kobo-docker's KPI image. Pack `20261111-1117`:
  36 GB, 22 images.
- **Fresh install** (`kobo-box-fresh`, `s-8vcpu-32gb-amd`, offline) from pack `20261111-1117`:
  19 min including first boot (`box-fresh-install-steps-20261111.txt`); KPI on the box's
  image, `ai-setup.py` applied at first boot. Offline: `e2e-nlp.py` PASS (text qual 3/3,
  photo 3/3 with 70 s for the first question, translation 26 s, transcription 0% WER);
  `e2e-dash.py` 23 ok, 0 failures; `e2e-dash-espo.py` PASS (5 cases of the team); knowledge,
  paper PASS; `e2e-espo.py --edge --share-with cases-bridge` 18/28 at first: no case within
  its 3 min, as designed on a new box (EspoCRM gets the form's select fields only when a
  form is shared with the bridge, by the 10-minute setup timer; the 10 visits waited in the
  ledger and became cases at its next run). The test now runs `espocrm.sh setup
  --if-form-changed` right after sharing, as the timer would: 28/28.

## 2026-11-11 (later): `gpu-6000adax1-48gb` (RTX 6000 Ada 48 GB, 8 vCPU, tor1), E4B tier

The GPU poller got one on its third round of a second try. `gpu-tiers.sh e4b`, offline
(egress checked blocked): `log-rtx6000ada-e4b-20261111.txt`,
`20261111-144342-rtx6000ada-gemma-4-E4B-it-Q4_0.gguf.json`, `vram-rtx6000ada-e4b-20261111.txt`.
All correct: qual on a transcript 3/3 (0.1 s each), on a typed answer 4/4 (0.1–0.2 s), on a
photo 3/3 (0.4 s for the first question with no prompt cache, then 0.2 s). Whisper 2.0% WER
at a median 93× real time (48–98×), translation 0.1–0.2 s, chrF 59.3 / 57.8. 6.0 GB of VRAM in
use; 179 W average (221 W peak) over the 19 s of tests. Kept up after the run (hard to get).

## 2026-11-11/12: the Gemma benchmark, phase 1 (`kobo-box-gpu2`, RTX 6000 Ada 48 GB, tor1, offline)

MODELS-PLAN.md. 31 recipes (`gpu-tiers.sh`), the extended test set (7 languages of FLEURS,
39 text and 36 photo qual cases): `gemma-phase1/` (`bench-phase1.md`, `by-language.txt`,
every run's JSON and log). Extended qual (75 cases) and speed per question on this GPU:

| Model | Q4_0 | Q8_0 | BF16 | VRAM (Q4, with Whisper) | s / question |
|---|---|---|---|---|---|
| E2B | 54 | 51 | 49 | 4.9 GB | 0.07 |
| E4B | 67 | 66 | 66 | 6.5 GB | 0.10 |
| 12B | 69 | 69 | - | 11.2 GB | 0.37 |
| 26B-A4B | 70 | 71 | - | 18.6 GB | 0.16 |
| 31B | 70 | 70 | - | 25.5 GB | 0.60 |

- **Quantization costs nothing measurable** from E4B up (Q4_0 = Q8_0 = BF16 within a case);
  E2B moves 49–54 between quants, i.e. it's near its limit on these cases.
- **Size:** E4B → 12B/26B/31B adds 2–4 cases, mostly photos (29 → 30–33 of 36). Text qual is
  37–39/39 from E4B up. 26B-A4B is the best value above E4B: 12B's score, half its time.
- **Thinking on:** E4B 69 (from 67, on photos); 12B 69 and 31B 70, the same as without. At
  20× the time (2–7 s a question), and translation got worse with it.
- **Image budget** (E4B): 560 tokens as good as the default (67), 280 loses 4 photo cases.
  Projector BF16 against Q8_0: no gain (66).
- **Speculative decoding** (MTP / DFlash drafts): same answers, no speed-up on this GPU
  (0.15 vs 0.16 s for 26B); the CPU rig is where it could matter (phase 2).
- **Transcription:** Gemma's audio (E2B/E4B; 26B and 31B have none) beats Whisper turbo on
  Swahili (E4B 27% vs 41%), Hausa (25–37% vs 104%) and Amharic (51–56% vs 124%); Whisper
  stays best on Spanish, French, Portuguese (2%). **12B's audio is broken** on those three
  languages: it loops (11–18 of 113 clips hit the 400-token cap; WER 130–1000%), and 12B
  also emits empty thought markers with thinking off. Not a kit model for audio.
- **Translation into English** (chrF, reference text): Spanish/French/Portuguese/Arabic all
  58–74 from E2B up; Swahili 59–68; Amharic 56–63; **Hausa the weak one** (E4B 40, 31B 53).
  **From English:** Hausa and Amharic are poor at every size (E4B 40/39, 31B 52/42), and 12B
  produced almost nothing usable in Hausa (chrF 2).
- **TranslateGemma** (with its own prompt): no better than the instruct model of the same
  size, often worse (from English: tg27 below 31B in all 7 languages; into English within
  ±3 except Hausa, where tg27-q8 reaches 56 against 31B's 53). Its qual scores are
  meaningless (a translation model). Not worth a place in the kit.
- Found on the way: llama-server drops TranslateGemma's language fields (fixed: the prompt is
  built by hand); `ai.env` values with spaces need quoting; a thinking run's log grows in
  bursts (Python's buffering through tee: fixed), and the watchdog wrongly stopped two
  thinking runs before that (rerun). Whisper turbo is 0.406 overall because of Hausa and
  Amharic.
- Weights deleted before parking (re-fetch with `models.sh fetch`, ~25 min); parked as
  `kobo-box-gpu2-snapshot`.
