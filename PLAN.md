# Kobo-in-a-box AI: plan

Goal: one field device that runs KoboToolbox fully offline, plus:

1. **AI processing in KPI**: transcription, translation and qual analysis, served by local open-weight models.
2. **AI agents**: OpenCode and OpenWork on a local model, using the Kobo MCP and data analysis tools, for field staff with no internet.

Status (2026-10-22): scoping done. DigitalOcean test scripts are written (see `README.md`) but nothing has been run yet. No droplets or other cloud resources exist.

Background: [Kobo-in-a-box prototype (Notion)](https://app.notion.com/p/590d02036dd542019116f3661cd1d62c). v0.1 ran Kobo offline on a ThinkPad X1 Carbon (8 GB RAM) with no AI. That laptop is too small for this plan.

### Pick up here

1. Read sections 1–3 below (about 10 minutes).
2. Answer the open questions in section 7, at least the pilot languages.
3. Start workstream **W1** in section 5: `./provision.sh` (it asks for confirmation before billing starts), then follow `README.md`.
4. Tick off boxes in section 5 as you go.

**Note:** the local checkouts in `~/kobo/` are old (`kpi` is from July 2024, `kobo-docker`/`kobo-install` from August 2024). They predate the subsequences rewrite and LLM qual analysis. Re-clone or pull before any KPI work.

---

## 1. Constraints that decide the hardware

| Constraint | Why it matters |
|---|---|
| **Kobo images are x86-only.** `kobotoolbox/kpi` and `kobotoolbox/enketo-express-extra-widgets` publish only `amd64` images on Docker Hub (checked 2026-10-21) | Any ARM device (Raspberry Pi, Jetson, DGX Spark, or a Mac without emulation) needs custom ARM builds of KPI, including its frontend, and of Enketo, maintained for every release. Emulating x86 with QEMU is too slow. |
| **Agents need long prompts processed fast.** OpenCode's system prompt plus tool and MCP definitions is roughly 10–20k tokens, re-sent on every turn (partly cached) | Prompt-processing speed, not generation speed, decides whether agents are usable. A CPU-only small board takes minutes per turn. |
| **Memory has to hold everything at once**: the Kobo stack (~4–6 GB), the transcription model (~1–2 GB), the batch NLP model, and the agent model with a 32–64k context | 64 GB is the practical minimum with agents; 128 GB is comfortable. |
| **Field conditions**: power from a battery or solar, heat and dust, customs, theft or seizure, local repair | Low-watt devices are better, DC or USB-C input is better, and the disk must be encrypted and unlock without someone typing a passphrase (TPM). |

## 2. Hardware options

Prices are approximate and unverified for Oct 2026. Speeds are community-reported ballparks to confirm on real hardware.

| Device | Arch | Memory | Power (load) | ~Cost | Kobo | KPI AI | Agents | Verdict |
|---|---|---|---|---|---|---|---|---|
| Raspberry Pi 5 16 GB (+ AI HAT+ 2, Hailo-10H, 8 GB, $200) | ARM | 16 GB | 5–15 W | $320 | Custom ARM builds | Tiny models only. Hailo runs vendor-compiled small models, not Gemma 4 GGUFs | No: minutes per turn | **Not suitable** for this. Fine for very low-power data collection only, once ARM images exist |
| Intel N150 mini PC | x86 | 16 GB | 10–25 W | $200 | Native | Too slow | No | Kobo-only box, no AI |
| NVIDIA Jetson Orin Nano Super | ARM + CUDA | 8 GB shared | 7–25 W | $250 | Custom ARM builds | Memory too small for Kobo plus models | No | Not suitable |
| NVIDIA Jetson AGX Orin 64 GB / Thor 128 GB | ARM + CUDA | 64/128 GB | 15–130 W | $2,000 / $3,500 | Custom ARM builds | Yes | Yes | Capable, but the ARM build burden and JetPack quirks rule it out |
| Ryzen AI 9 HX 370 / 8845HS mini PC, 64–96 GB | x86 | 64–96 GB | 30–65 W | $800–1,200 | Native | Yes, models run on the built-in GPU via Vulkan | Borderline: 26B-A4B usable, slow first turn | **Budget option** |
| **Ryzen AI Max+ 395 ("Strix Halo"), 128 GB** e.g. Framework Desktop, GMKtec EVO-X2, HP Z2 Mini G1a; laptops: HP ZBook Ultra G1a, ASUS ROG Flow Z13 | x86 | 128 GB unified, ~96 GB usable by the GPU | 50–120 W (configurable TDP) | $2,000–2,800 (mini PC), more for laptops | Native | Yes | **Yes, even gpt-oss-120b** | **Recommended** |
| RTX laptop (8 GB VRAM, 64 GB RAM) | x86 | 8 GB VRAM + RAM | 100–180 W | $1,500–2,200 | Native | Yes, fast | Small agent models only (VRAM-bound) | Good for KPI AI. Battery and screen built in |
| Mac mini M4 Pro 64 GB | ARM | 64 GB unified | 40–70 W | $2,000 | Containers via Rosetta; models run natively on macOS | Yes | Yes | Workable, but less like an appliance, harder to repair or replace in the field, Docker runs inside a VM |
| DGX Spark / ASUS GX10 (GB10) | ARM + CUDA | 128 GB | up to ~170 W | $3,000–4,000 | Custom ARM builds | Yes | Yes | Overkill and ARM |

### Recommendation

- **Primary: a Strix Halo 128 GB machine.**
  - Kobo's x86 images run unmodified.
  - Unified memory holds gpt-oss-120b (~63 GB). That's the model KPI's cloud qual analysis already uses as its primary, so one model and one set of prompts work both online and offline. There's still room for Gemma 4 and Whisper.
  - It has a TPM, so the encrypted disk can unlock at boot without a passphrase.
  - Set the TDP to 45–65 W when running on battery.
- **Form factor:** a mini PC is cheaper and swappable. A Strix Halo laptop has its own battery (a built-in UPS), screen and keyboard. Decide after a pilot.
- **Raspberry Pi: no.** It fails both the x86 constraint and the agent-speed constraint. Revisit only if Kobo starts publishing multi-arch images, and then only for a no-AI kit.
- **Buy one Strix Halo unit early as the development box.** DigitalOcean can't reproduce unified-memory performance, so the cloud rig (README) covers functional and offline testing, and the unit covers real performance and power.

### Field kit additions

- Power station of 500 Wh or more with a 100–200 W solar panel. Prefer devices with USB-C power input (check the model; some mini PCs take AC only).
- A travel router or Wi-Fi access point (already in v0.1).
- Dust filters, and a case with airflow.

## 3. Software architecture on the box

```
                    ┌──────────────── field LAN (Wi-Fi AP) ────────────────┐
 KoboCollect/Enketo │  staff browsers: Kobo UI · OpenCode web · (OpenWork) │
                    └───────────────┬──────────────────────────────────────┘
                                    │ edge nginx :80 (kobo.local library, kf/kc/ee → Kobo :8080, opencode.local)
 ┌──────────────────────────────────┴──────────────────────────────────────┐
 │ kobo-docker: KPI · Enketo · Postgres · Mongo · Redis · Celery           │
 │   └─ subsequences (local NLP backend) ──┐                               │
 │                                         ▼                               │
 │ inference: llama-server(s) ── whisper-server                            │
 │   batch model:  Gemma 4 E4B / 26B-A4B  (translation, qual)              │
 │   agent model:  gpt-oss-120b or Gemma 4 26B-A4B (tool calling)          │
 │                                         ▲                               │
 │ agents: OpenCode server(s) ─── kobo-mcp (stdio/HTTP) ── KPI API         │
 │          └─ analysis sandbox (Python, DuckDB, pandas, LibreOffice…)     │
 └─────────────────────────────────────────────────────────────────────────┘
```

### 3a. KPI AI processing

On kpi `main`, the AI features are three narrow backend integrations in `kobo/apps/subsequences/`:

| Feature | Upstream today | Local replacement |
|---|---|---|
| Transcription | `actions/automatic_google_transcription.py` → `integrations/google/google_transcribe.py` (Google Speech; long audio goes through a Cloud Storage bucket and Google's long-running operations) | whisper.cpp server (or Gemma 4 E4B audio) |
| Translation | `actions/automatic_google_translation.py` → `integrations/google/google_translate.py` | Gemma 4 via llama-server |
| Qual analysis | `actions/automatic_bedrock_qual.py`: Bedrock `invoke_model`, primary **gpt-oss-120b**, fallback Claude Sonnet. Prompts and strict parsers in `prompts.py` | The same prompts, sent to a local OpenAI-compatible endpoint |

Approach:
- **Switch with a setting.** Put the local backends behind `NLP_BACKEND=local` and keep the existing action IDs, because the frontend hardcodes them in about 25 files under `jsapp/`. A provider-neutral action ID is the cleaner design if this is merged upstream, but it needs frontend work.
- **Transcription and translation services** implement `process_data()` like the Google services do (`integrations/google/base.py`). Swap the Google long-running-operation and cache pattern for Celery tasks (`allow_async=True`; bulk actions pass a `bulk_action_uid`).
- **Qual analysis:** only `create_bedrock_client()`, `get_response_from_llm()` and the `LLModel` list are Bedrock-specific. Keep `prompts.py` and its parsers. Note that `parse_choices_response` requires exactly `TRUE,FALSE,…`, so smaller models may need prompt or parser tweaks; the smoke test checks this.
- **Language tables:** the `languages` app's tables drive the UI's language picker. Seed them with only the languages the box supports.
- **Usage limits:** check that usage limits and counters (`update_nlp_counter`, `UsageType`) are harmless with no Stripe.
- Estimate: 2–4 developer-weeks.

### 3a-bis. Models for KPI AI

All of these allow commercial use. **Avoid NLLB-200**: its licence is non-commercial (CC-BY-NC).

| Job | First choice | Alternatives / notes |
|---|---|---|
| Transcription | **Whisper large-v3-turbo** (MIT), via whisper.cpp | Gemma 4 E4B audio. The model card reports about 8% error on FLEURS, a standard multilingual speech benchmark, but **clips are capped at 30 s**, so you'd need your own chunking. Whisper medium for CPU-only boxes |
| Translation | **Gemma 4** (Apache 2.0): E4B on small boxes, 26B-A4B on larger ones | Pre-trained on 140+ languages, about 35 supported out of the box. Minority languages need a LoRA fine-tune or community models (e.g. Padauk/AI4Burmese) |
| Qual analysis | **gpt-oss-120b** on a 128 GB box: same model as KPI's cloud qual | Gemma 4 26B-A4B or E4B on smaller boxes |
| Inference server | llama.cpp `llama-server`: OpenAI-compatible, CUDA/Vulkan/CPU | Ollama. Google's LiteRT-LM suits running inside an app more than serving several users |

All GGUF files are on Hugging Face without login (`ggml-org/gemma-4-*-GGUF`, `ggerganov/whisper.cpp`). Sizes: E4B Q4_0 4.6 GB, 26B-A4B Q4_0 14.6 GB, whisper turbo q8 0.9 GB.

### 3b. Agents: OpenCode + OpenWork

**OpenCode** (MIT) is the core. It talks to llama-server through the OpenAI-compatible provider and supports MCP servers in `opencode.json`.
- Field staff use **`opencode web --hostname 0.0.0.0 --mdns`** from any laptop or tablet browser, with `OPENCODE_SERVER_PASSWORD` set. No install on staff devices.
- One OpenCode instance per user or workspace, each in its own container. Multi-user use is the main open question to test.

**OpenWork** (MIT core; the `ee/` control plane "Den" is not needed). It's a desktop app built on OpenCode, friendlier for non-technical staff. Two ways to deploy it:
- **(a) Desktop app on staff laptops**, set to use the box's LLM as a custom model and the box's MCP server. Needs the app pre-installed.
- **(b) Browser version on the box.** Today this is a developer launcher (`pnpm world up dev-app-web`), not a production server, so it needs work or upstream support.

**Start with OpenCode web and treat OpenWork as phase 2.**

**Offline gotchas to test** (the droplet's offline mode is designed to catch these):
- Auto-update checks: set `autoupdate: false`.
- Fetching the online model catalogue: define the provider and model explicitly in config.
- Telemetry, plugin or font downloads, and OpenWork's Den and cloud calls.

### 3c. kobo-mcp on the box

`kobotoolbox/kobo-mcp` (private, Python, has a Dockerfile) already covers most of what field analysis needs:
- `summarize_submissions`, `find_duplicates`, `get_submission_stats`, `export_data`
- validation workflows
- the built-in **Weekly digest** and **Data quality review** prompts

Changes needed:

| Change | Why |
|---|---|
| **Allow `http://` for trusted hosts.** `servers.py` rejects any non-https Kobo URL; add a flag that allows http for `EXTRA_KOBO_HOSTS` only (e.g. `kpi:8000` or `kf.kobo.local`) | The box runs over HTTP. The alternative is local HTTPS with a box-specific certificate authority, which also helps Enketo's offline mode but means installing a CA on every device |
| Run in **stdio mode** per OpenCode instance (`KOBO_TOKEN`, `KOBO_BASE_URL`), or HTTP mode with a token header per user | Each user's agent acts only with that user's Kobo permissions |
| Turn off email notifications (needs Resend, i.e. internet) and dashboards (`kobo-dash`) | Online-only features |
| `preview_form` falls back to a text outline in clients without MCP Apps support | OpenCode/OpenWork support for MCP Apps is unverified |
| In OpenCode config, set `permission` to **deny** `delete_submissions` and `delete_project` by default, and **ask** before other write tools | Smaller local models make more mistakes, and Kobo has no trash |

### 3d. Analysis sandbox

The agent's shell tool runs in a container with everything pre-installed. Nothing can be installed with pip or apt once offline.
- **Python:** pandas, polars, duckdb, pyarrow, matplotlib, plotly (static export), scipy, statsmodels, openpyxl, python-docx, weasyprint
- **Documents and reports:** LibreOffice (headless), pandoc
- **GIS (optional):** R plus tidyverse, geopandas
- **Mounts:** a per-user workspace directory. No access to Kobo's databases; Kobo data arrives only through kobo-mcp or exports.
- **Skills:** OpenCode/OpenWork skills for common jobs (weekly digest, data quality review, donor one-pager, cleaning log), reusing kobo-mcp's prompts.

### 3e. Model serving and contention

- **Two llama-server instances:**
  - batch NLP model (Gemma 4 E4B, or 26B-A4B for translation/qual), driven by a Celery queue with concurrency 1–2;
  - agent model with 2–4 parallel slots and a 32–64k context per slot.
- **Agent model candidates**, tested on tool-call reliability with the kobo-mcp tools:
  1. **gpt-oss-120b**: same model as KPI's cloud qual, ~63 GB, 128 GB box only.
  2. **Gemma 4 26B-A4B**: native function calling, ~15 GB.
  3. Qwen3-Coder-30B-A3B or gpt-oss-20b as fallbacks.
- **Priority:** interactive agents first. Batch transcription runs overnight or when on mains or solar power.

### 3f. Security

- The disk is encrypted and unlocks via the TPM. Agent session histories hold personal data: keep them on the encrypted disk and set a retention and purge policy.
- Agents act with the logged-in user's Kobo token. Use read-only Kobo accounts by default for analysis.
- Passwords on OpenCode web and every service. Wi-Fi with WPA3 or a strong WPA2 passphrase. No services exposed beyond the LAN.
- The box has no internet, so nothing leaks out. The risk is on-device access: a stolen box, or an untrusted device joining the Wi-Fi.

### 3g. Offline library and edge proxy

Proven in the Jamaica pilot (2026-03): nginx serving a folder at `kobo.local`, so staff
downloaded the KoboCollect APK from the laptop. This makes it part of the build.

- **One landing page at `http://kobo.local`** for any device on the box's Wi-Fi: a link
  to Kobo, the KoboCollect server URL, user guides, and installers grouped by Android,
  Windows and macOS, each with version, size and SHA-256. Nothing on it loads from the
  internet.
- **Edge nginx owns port 80.** kobo-install runs in its reverse-proxy mode (`proxy: True`,
  `nginx_proxy_port: 8080`, set in `kobo-setup.py`), so Kobo's nginx config is never
  edited and survives upgrades. The edge sends `kf.*`/`kc.*`/`ee.*` to `127.0.0.1:8080`
  and everything else to the library. OpenCode web (W4) and a health page join here later.
- **Manifest-driven content** (`remote/library/manifest.tsv`): id, section, version, URL,
  SHA-256. `library.sh fetch` downloads and verifies; sources without published checksums
  (QGIS) are pinned from the first download. `library.sh docs` builds the Kobo user guide
  from `kobotoolbox/docs` (Sphinx; en, es, fr) with the Google Analytics tag removed.
  `render.py` writes the landing page. `library.sh check` fails if any page would load an
  external script, stylesheet, font or image.
- **First set (~4 GB):** KoboCollect; QField (arm64 + 32-bit), the field app for QGIS
  projects; QGIS 3.44 LTR (Windows, macOS); LibreOffice (Windows, macOS on Apple silicon
  and Intel), for editing XLSForms and opening exports with no internet; Kobo user guide;
  QGIS documentation (HTML, en/es/fr), plus the training manual and the introduction to
  GIS as PDFs.
- **Later candidates:** ODK Collect docs, Kiwix (`kiwix-serve` + ZIMs such as WikiMed and
  Wikipedia in the pilot languages), Organic Maps with regional map files, offline
  basemaps (MBTiles) for QGIS/QField, a read-only shared folder for the team.
- **Local DNS for phones.** Android browsers don't reliably resolve multi-label mDNS names
  like `kf.kobo.local`, so avahi (v0.1) isn't enough. When the box is the access point
  (a USB Wi-Fi dongle, as in Jamaica), NetworkManager's hotspot plus dnsmasq answers
  `kobo.local` and `*.kobo.local` with the box's IP. Keep avahi as a fallback for when
  the box joins another router.

#### Provisioning new boxes

Content is downloaded **once on an online build machine** into a *content pack* (library,
model weights, `docker save` image tarballs, `.deb`s) and copied to each box. Nothing is
fetched in the field.

1. **Script (now):** `install.sh --pack <dir>` on stock Ubuntu: debs, `docker load`,
   `kobo-setup.py`, library + models, systemd units so everything starts on boot. On the
   DigitalOcean rig the droplet is the build machine (`library.sh build`).
2. **One USB, unattended (target):** stock Ubuntu 26.04 LTS ISO plus autoinstall, not a
   remastered ISO. The stick holds the ISO, a `CIDATA` partition with `autoinstall.yaml`
   (LUKS with TPM unlock, user, packages), and a `KOBOPACK` partition with the content
   pack; `late-commands` runs `install.sh` from it. Updating a kit means copying a new
   pack, not rebuilding an ISO. Remaster (Cubic, livefs-editor) only if a single `.iso` is
   required.
3. **First boot, per box:** `firstboot.sh` generates the secrets every box must not share
   (Kobo passwords and Django secret, Wi-Fi SSID and passphrase, LUKS recovery key,
   hostname) and prints a label card with the Wi-Fi QR code, admin password and recovery
   key. This is why we don't clone a golden disk image: every clone would share secrets.

## 4. Testing on DigitalOcean (extends README)

The DigitalOcean rig covers **functional and offline** testing. Performance numbers only count from a real Strix Halo unit.

| Phase | Droplet | What to test |
|---|---|---|
| A. Kobo + KPI AI | `gpu-4000adax1-20gb` | As in README: Whisper, Gemma 4, smoke test, offline mode |
| B. Agents (small model) | same | OpenCode web + self-hosted kobo-mcp (with the http patch) + sandbox, on Gemma 4 26B-A4B (fits in 20 GB). Tool-calling success rate on 20–30 scripted tasks, built from the kobo-mcp README's example prompts |
| C. Agents (large model) | `gpu-6000adax1-48gb` with MoE expert layers offloaded to RAM (`--n-cpu-moe`), or `gpu-mi300x1-192gb` for a few hours | gpt-oss-120b against the same task set |
| D. Offline hardening | any, with `offline.sh on` | Watch for any outbound attempt by OpenCode, OpenWork or kobo-mcp (log DNS failures). Everything must work from cold boot with no internet |

Additions to the scripts once the plan is approved:
- an `agents` compose profile: OpenCode web, kobo-mcp, sandbox image;
- a second llama-server for the agent model;
- a task-set runner that scores tool-call success.

## 5. Workstreams

Effort figures are rough, for one developer. W1, W2 and W3 can run in parallel.

### W1. DigitalOcean rig: Kobo + models offline (~1 week, ~$30–50 of GPU time)
Current status and next steps: [STATUS.md](STATUS.md).
- [x] `./provision.sh`, then `bootstrap.sh` on the droplet (`README.md`). CPU droplet only so far: no GPU stock
- [x] Install a current Kobo release with kobo-install (`kobo-setup.py`)
- [ ] `./ai.sh up gpu` and `smoke-test.py` online, then again after `./offline.sh on` (done on CPU)
- [ ] Add real test clips for the pilot languages to `/opt/models/audio/` (FLEURS Spanish added)
- [ ] Run the tier recipes in the README (CPU-only, 8 GB GPU, 20 GB GPU) and keep the `results/*.json`
- [ ] Record whether Gemma audio input works in llama.cpp, and the qual `PARSE FAIL` rate per model
- [ ] `./park.sh` after every session

### W2. KPI local NLP backend (~2–4 weeks)
- [ ] Fresh kpi clone on `main`; branch `local-nlp-backend`
- [ ] `NLP_BACKEND` setting; qual analysis → OpenAI-compatible client (first, smallest change)
- [ ] Local translation service → llama-server
- [ ] Local transcription service → whisper-server, as Celery tasks; bulk actions work
- [ ] Seed the language tables for the pilot languages; check usage limits on self-hosted
- [ ] Tests, then deploy to the droplet and run through the UI while offline
- [ ] Talk to the KPI team about merging a provider-neutral backend upstream

### W3. kobo-mcp offline profile (~2–3 days)
- [ ] Flag to allow `http://` for `EXTRA_KOBO_HOSTS` only (`src/kobo_mcp/servers.py`)
- [ ] Offline config profile: email notifications and dashboards off
- [ ] Recommended OpenCode `permission` config: deny the delete tools, ask before writes

### W4. Agents on the rig (~1–2 weeks, after W1 + W3)
- [ ] `agents` compose profile: OpenCode web (password, `autoupdate: false`, explicit provider and model), kobo-mcp, analysis sandbox image
- [ ] Second llama-server for the agent model (Gemma 4 26B-A4B on the 20 GB droplet)
- [ ] Task set: about 30 field-analysis tasks based on the kobo-mcp README example prompts, plus a runner that scores tool-call success and time
- [ ] gpt-oss-120b run (phase C: 48 GB droplet with `--n-cpu-moe`, or MI300X for a few hours)
- [ ] Offline hardening: no outbound attempts from OpenCode, OpenWork or kobo-mcp; cold boot works
- [ ] Decide multi-user model: one OpenCode per user vs shared server

### W5. Hardware (~$2,000–2,800 + power kit)
- [ ] Buy one Strix Halo 128 GB dev unit (mini PC vs laptop; check for USB-C/DC power input)
- [ ] Re-run W1/W4 benchmarks on it at full power and at the 45–65 W cap; log power draw from the wall
- [ ] Size the power station and solar panel from the measured watt-hours
- [ ] Update the Notion shopping list

### W6. OpenWork (phase 2)
- [ ] Desktop app on a staff laptop, pointed at the box's LLM and kobo-mcp
- [ ] Ask the OpenWork maintainers about a supported browser/server mode (today it's only a dev launcher)

### W7. Package and pilot
- [ ] One install from USB; weights preloaded; services start on boot; health page (built in W8)
- [ ] Skills pack (weekly digest, data quality review, donor one-pager, cleaning log)
- [ ] Staff quick-start guide (connect to the Wi-Fi, open Kobo and OpenCode in the browser)
- [ ] Pilot with one partner (FAO Tanzania or SGDD Turkey), with power and heat logging

### W8. Offline library and edge proxy (~1–2 weeks; see 3g)
- [x] `remote/library/`: manifest (Collect, QField, QGIS LTR, LibreOffice, QGIS docs), `library.sh` fetch/docs/render/check, edge nginx compose
- [x] `kobo-setup.py`: kobo-install proxy mode (Kobo nginx on 8080); `--reconfigure` for existing installs
- [ ] On the droplet: `library.sh build`, pin the QGIS checksums it prints, `kobo-setup.py --reconfigure`, `library.sh up`
- [ ] Check through the edge: Kobo login, form deploy, Enketo, KoboCollect submission with media; library downloads resume (range requests)
- [ ] `offline.sh on`, then `library.sh check` and load every guide with outbound blocked
- [ ] Wi-Fi hotspot + dnsmasq for `kobo.local`/`*.kobo.local` (physical box or a spare laptop with a USB Wi-Fi dongle); install the APKs on a real Android phone over HTTP
- [ ] Landing page: KoboCollect configuration QR code and Wi-Fi QR code (per box, from firstboot)
- [ ] Content pack layout + `install.sh --pack` (debs, `docker save` images, models, library)
- [ ] Ubuntu 26.04 autoinstall USB (`CIDATA` + `KOBOPACK` partitions), LUKS + TPM
- [ ] `firstboot.sh`: per-box secrets and label card
- [ ] Second content batch: pick from the 3g candidates once pilot languages are known

## 6. Risks

| Risk | Mitigation |
|---|---|
| Transcription and translation quality in pilot languages | Evaluate before buying: about 50 clips per language scored against human transcripts; fine-tune or pick a community model where needed |
| Smaller models break qual analysis's strict answer format | The smoke test measures the parse-fail rate; adjust prompts or parsers per model; prefer gpt-oss-120b on 128 GB boxes |
| Agents make mistakes with write tools | Delete tools denied, write tools ask first, read-only Kobo accounts by default |
| Hidden internet dependencies (update checks, model catalogues, fonts, cloud calls) | Offline mode on the droplet (W1, W4) |
| Maintaining a fork of KPI and kobo-mcp | Aim to merge the provider-neutral NLP backend and the kobo-mcp offline profile upstream |
| Weights are 5–65 GB | Preload on the image or USB stick; never download in the field |
| Phones can't resolve `*.kobo.local` (mDNS) | The box runs DNS (dnsmasq) when it is the access point; the bare IP still serves the library |
| Installers and docs go stale on boxes in the field | Versions pinned in `manifest.tsv`; the landing page shows the build date; refresh the content pack before each deployment |
| Power and heat in the field | Batch jobs on mains or solar; capped TDP on battery; measure in the pilot |
| x86-only images lock out cheap ARM boards | Accept for now; revisit if Kobo publishes multi-arch images |

## 7. Open questions

- Multi-user OpenCode: one instance per user, or a shared server with workspaces? How is a user's Kobo token passed into their MCP session?
- Which 3–6 languages for the pilot? This drives the transcription and translation evaluation and any fine-tuning (e.g. Padauk for Burmese).
- Does Kobo want to publish multi-arch (ARM) images upstream? That would reopen Raspberry Pi, Jetson and Mac for no-AI kits.
- HTTP vs local HTTPS on the box. Affects Enketo offline mode, kobo-mcp, and secure cookies.
