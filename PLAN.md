# Kobo-in-a-box AI: plan

Goal: one field device that runs KoboToolbox fully offline, plus:

1. **AI processing in KPI**: transcription, translation and qual analysis, served by local open-weight models.
2. **AI agents**: OpenCode and OpenWork on a local model, using the Kobo MCP and data analysis tools, for field staff with no internet.
3. **Dashboards**: the agent builds live analysis dashboards (kobo-dash, through kobo-mcp's dashboard tools) that anyone on the box's Wi-Fi can open (3h).
4. **Local knowledge base**: a RAG over Kobo, ODK and XLSForm docs plus whatever the deployment adds, exposed to the agent as MCP tools (3i).

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
 │ agents: OpenCode server(s) ─┬─ kobo-mcp (HTTP, OAuth) ── KPI API         │
 │          │                  │     └─ dashboard tools ── kobo-dash (web,  │
 │          │                  │          worker) ── KPI API (view account) │
 │          │                  └─ kobo-knowledge MCP ── pgvector + FTS      │
 │          │                        └─ embeddings/reranker (llama-server)  │
 │          └─ analysis sandbox (Python, DuckDB, pandas, LibreOffice…)     │
 │ box Postgres (kobo-dash, knowledge; separate from Kobo's own Postgres)  │
 │ edge: dash.kobo.local · mcp.kobo.local · tiles (/tiles) · /docs         │
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
| Turn off email notifications (needs Resend, i.e. internet). **Keep dashboards, pointed at the box's own kobo-dash** (3h) | Email is online-only; dashboards can run on the box |
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
  from `kobotoolbox/docs` (Sphinx; en, es, fr) for offline use: the Google Analytics tag
  removed, Google Fonts downloaded and served locally, and absolute `support.kobotoolbox.org`
  links pointed at the local copy.
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

### 3h. Dashboards on the box (kobo-dash)

Reviewed 2026-10-28: `kobo-mcp` `main` (45 commits ahead of `production`; all dashboard
tools are on `main` only) and `kobo-dash` `main`. Neither calls an LLM, loads a CDN or
sends telemetry; fonts and JS are bundled, and maps are kobo-dash's own SVG plus raster
tiles. So the agent-built dashboards can run on the box. What stops them today:

| Blocker | Where | Change |
|---|---|---|
| Dashboards only allowed on kf and eu | kobo-mcp `tools/dashboards.py:42` (`DASH_SERVERS`, hardcoded); kobo-dash `ALLOWED_SERVERS` (setting) and `assertions.py` | Make `DASH_SERVERS` a setting (e.g. defaulting to `ALLOWED_SERVERS`-style list); set both to the box's `kf.kobo.local`. kobo-dash plan already says private servers are "an allow-list change" |
| https required to reach Kobo | kobo-mcp `servers.py` (also rejects IP literals; private addresses only via `EXTRA_KOBO_HOSTS`); kobo-dash `kobo.py:67` | Same trusted-host http flag as W3, in both repos. Or local HTTPS (see the open questions in section 7) |
| Basemap tiles from tile.openstreetmap.org; `tile_origin` accepts only https | kobo-dash `config.py:62`, `TILE_URL` | Serve raster tiles for the deployment region from the box (`/tiles/{z}/{x}/{y}.png`); allow an http tile origin for trusted hosts. Render the tiles at build time from an OSM extract (Geofabrik + OpenMapTiles/tileserver-gl), not by scraping OSM's tile servers (their usage policy forbids bulk download). The same MBTiles serve QGIS/QField (3g's "offline basemaps"). Empty `TILE_URL` (no basemap; shapes and points still draw) is the fallback |
| Admin boundaries fetched from the geoBoundaries API (redirects to GitHub) | kobo-dash `boundaries.py:36`, tool `fetch_dashboard_boundaries` | Pre-fetch ADM0–ADM2 GeoJSON for the deployment countries into the content pack; a `BOUNDARIES_DIR` setting makes the fetch read from it. Today's workaround is the admin GeoJSON upload (browser only, 3 MB / 5,000 features) |
| `desk_review` relies on the agent's web search (OCHA, HDX, ReliefWeb); evidence sources must be https URLs with a dotted hostname | kobo-mcp `prompts.py`, kobo-dash `evidence.py:157` | Offline variant of the prompt that searches the local knowledge base (3i) instead, with documents such as the HNO, earlier assessments and cluster guidance loaded before deployment; accept `http://kobo.local/...` as an evidence source |
| Owner sign-in to the dashboard admin goes through kobo-mcp's OAuth (`/sso/authorize`, PKCE); `dash_enabled` needs `OAUTH_KEYS` + `DASH_URL` + `DASH_SIGNING_KEY` | kobo-mcp `config.py:55`, kobo-dash `login.py` | Run **one** kobo-mcp in HTTP mode with OAuth on (`mcp.kobo.local`), not stdio per user. Users paste their Kobo token once on its `/login` page; OpenCode connects as an OAuth MCP client (to test: OpenCode's remote-MCP OAuth with no internet). This also answers part of open question 1 (how the user's token reaches their MCP session) |
| Defaults point at kobolabs.dev | `PUBLIC_URL`, `MCP_URL`, `DASH_URL`, `ALLOWED_SERVERS` | Set in the box's env; per-box `SECRET_KEY`, `CRED_KEYS`, `OAUTH_KEYS`, Ed25519 dash key pair generated by `firstboot.sh` |

Running it:
- **Services:** kobo-dash `web` + `worker` (the poller) from one image, `alembic upgrade
  head` on start, and a box Postgres 17 (shared with 3i, separate from Kobo's own Postgres
  so Kobo upgrades never touch it). Images built online and `docker save`d into the pack;
  the Dockerfiles need npm, PyPI and ghcr.io at build time only.
- **Edge:** `dash.kobo.local` and `mcp.kobo.local` join the edge nginx. Dashboards open at
  `dash.kobo.local/d/<slug>`; live updates use SSE, so the edge must not buffer
  `/api/d/*/events`. Containers reach Kobo at `kf.kobo.local` via `extra_hosts`.
- **Dashboard account:** kobo-dash reads data with a per-owner view-only Kobo account
  (e.g. `alice_dash`) whose token the owner pastes in `/admin/kobo-access`. The box's
  user-creation script creates the pair.
- **Sharing on a LAN:** "public" means anyone on the box's Wi-Fi. Keep the default
  (offline, i.e. unpublished) and use password-protected dashboards for anything sensitive.
- **Hub kits:** dashboards run on the hub over the combined data; they refresh as field
  kits sync in.

Fit with local models (measured from the source):
- kobo-mcp's 63 tool descriptions are ~60k characters (~15k tokens; ~20–25k with schemas),
  on top of OpenCode's 10–20k. The dashboard and evidence tools are ~6.5k tokens of that,
  and `update_dashboard`'s `ops` parameter alone embeds `SPEC_HELP` + `DATASETS_HELP`
  (~4k tokens).
- The spec is a nested JSON DSL (pages, rows, scrolly steps, datasets with
  lookup/rollup/recode, calculated fields, shading), edited as op lists. `write_story` and
  `desk_review` are long multi-step workflows. Expect gpt-oss-120b to cope and 26B-A4B to
  struggle.
- Mitigations: **tool profiles** (an env setting that registers only a named set, e.g.
  `analysis`, `dashboards`, `forms`; today only dashboard and email tools are conditional);
  start every dashboard from `generate_dashboard_layout` (server-side, no spec writing) and
  have the model make small edits; a shorter `SPEC_HELP` for small models; 64k context per
  agent slot. W4's task set gets ~10 dashboard tasks to measure this.
- No MCP App is involved: the only one is the form preview. Dashboards are ordinary web
  pages, so they work whatever the agent client supports.

### 3i. Local knowledge base (RAG)

Reviewed 2026-10-28: `kobo-support-bot-poc` `main` (Django; Voyage `voyage-3-lite`
embeddings, Cloudflare Vectorize, Anthropic). Its older `migrate-django-bedrock-do` branch
already has the shape we need offline but was never run: an OpenAI-compatible client for
`/v1/embeddings` and chat, `bge-m3` at 1024-d, and a pgvector `DocChunk` table with an HNSW
index and a `manage.py index` command. `main` reverted those parts.

**Aim:** the agent answers "how do I…" questions about Kobo, KoboCollect, XLSForm, ODK and
QGIS, and questions about the deployment's own documents (SOPs, protocols, the assessment
ToR, sector guidance), from material on the box, citing pages that open offline.

Design:
- **One small service, `kobo-knowledge`** (in this repo, `remote/knowledge/`): an indexer,
  a search API and an MCP server (streamable HTTP at `mcp.kobo.local/knowledge`, registered
  in OpenCode next to kobo-mcp). Not the support bot's Django app: its forum search, token
  budgets, widget and analytics are cloud-service concerns. Keep it separate from kobo-mcp,
  because knowledge is box-wide while kobo-mcp acts per Kobo account.
- **Tools:** `search_knowledge(query, collections?, lang?, k=8)` → chunks with title,
  section, collection, language, score and a local URL; `read_document(url)` → the whole
  page or file as text; `list_collections()`. An OpenCode instruction (AGENTS.md / skill):
  use `search_knowledge` before answering how-to questions, cite the local URLs, say so when
  the knowledge base doesn't cover it (the bot's `[NO_DOCS]` rule).
- **Reuse from the support bot:** the heading-aware chunker (`indexer.py`: split at H2–H4,
  merge to ~1,600 chars, split above ~2,400, prefix `[Article] [Section]`); the per-source
  boost and one-language-per-article ranking (`backend/chat/rag.py`, re-tuned: the 0.35
  threshold and boosts were set for Voyage); the system-prompt rules and terminology list
  (`backend/chat/prompts.py`); the ~68 eval cases and deterministic checks
  (`backend/evals/`), including multilingual, hallucination-bait and prompt-injection
  cases.
- **Models** (all run on llama-server, permissive licences):
  - embeddings: **bge-m3** (MIT, ~0.6 GB at Q8, 1024-d, 100+ languages, so a question in
    Swahili finds an English page). Qwen3-Embedding-0.6B (Apache 2.0) as the alternative;
    pick by retrieval recall on the eval set;
  - reranking: **bge-reranker-v2-m3** (Apache 2.0) via `llama-server --reranking`, if the
    evals show it is worth the latency;
  - answers come from the agent model itself; the service only retrieves.
- **Store:** pgvector (HNSW, cosine) plus Postgres full-text search for hybrid retrieval
  (rank fusion), in the box Postgres from 3h. Exact terms (`select_one_from_file`,
  `pulldata`, error messages) are where pure vector search misses. A few thousand chunks;
  size is not an issue.
- **Index once, ship it:** the build machine embeds the standard corpus and the pack ships
  the index (a `pg_dump` with the embedding model's name and hash). The box only embeds
  what is added locally, with the same model; changing the model means re-embedding
  everything.
- **Citations open offline:** index the same pages the library serves, so a citation is
  `http://kobo.local/docs/kobo/es/...` and not support.kobotoolbox.org. The library
  manifest gets an `index` column; `library.sh docs` output feeds the indexer.

Corpus (check each licence before shipping):

| Collection | Source | Notes |
|---|---|---|
| Kobo user guide (en, es, fr) | `kobotoolbox/docs`, already built by `library.sh docs` | Same source as the support bot's `kobo-docs/` (118 en, 141 es, 141 fr pages) |
| XLSForm | xlsform.org + its reference table | Scraped by the bot's `scraper.py` |
| ODK | `getodk/docs` (Collect, form design, maps) | The bot takes 22 curated pages; take the repo |
| ODK XForms spec | getodk.github.io/xforms-spec | Low boost: for edge cases |
| QGIS / QField | Already in the library (3g) | |
| KoboToolbox Academy, kobotoolbox.org | `scraper.py` | Ask whether the Academy content may be redistributed |
| Community forum | — | Not indexed by the bot (it searches Discourse live). An offline snapshot of solved threads needs permission; treat as later |
| **Deployment knowledge** | Added per kit | See below |

Adding local knowledge:
- **Phase 1:** a `knowledge/<collection>/` folder per kit, filled before deployment (or by
  the focal point). `knowledge.sh add <dir> --collection <name>` converts PDF, DOCX, ODT,
  HTML and Markdown to text (pdftotext, pandoc, LibreOffice headless; OCR off by default),
  copies the original to the library so citations open it, and embeds. A small sidecar
  (`collection.yml`) gives a title, language and boost.
- **Phase 2:** an upload page on the library (behind the focal point's password), and
  an admin-maintained local FAQ (the bot's `FaqEntry` idea: short answers that always win,
  e.g. "which project do I submit to", "who to call").
- **Not for personal data.** The knowledge base is shared by everyone who uses the agent.
  Submissions stay in Kobo and reach the agent only through kobo-mcp with the user's own
  permissions.
- **Prompt injection.** Added documents are untrusted text that the agent reads while it
  holds write tools. Mark retrieved text as quoted material in the tool output, and rely on
  the existing safety net (deletes denied, writes ask first). Run the bot's injection
  cases against the local setup.

Later: the support bot's chat widget on the `kobo.local` landing page and in KPI, backed by
`kobo-knowledge` and the box's model, for staff who never open the agent. If the support
bot finishes the pgvector + OpenAI-compatible path (its `django-admin-logging.md` "Later"
item), the online bot and the box can share one retrieval backend.

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
Done 2026-10-28 on kobo-mcp branch `w3-offline-box`; details in [STATUS.md](STATUS.md).
- [x] Flag to allow `http://` for `EXTRA_KOBO_HOSTS` only (`HTTP_KOBO_HOSTS`)
- [x] Offline config profile: email notifications off; dashboards on and pointed at the box (`DASH_KOBO_HOSTS`; kobo-dash's half still to do, W9)
- [x] Tool profiles: register only a named set of tools, to shorten the prompt for small models (`TOOL_PROFILES`)
- [x] Recommended OpenCode `permission` config: deny the delete tools, ask before writes (`remote/agents/opencode.json`; MCP permission keys to verify in W4)

### W4. Agents on the rig (~1–2 weeks, after W1 + W3)
- [x] `agents` compose profile: OpenCode web (password, `autoupdate: false`, explicit provider and model), kobo-mcp, analysis sandbox image (`remote/agents/`, 2026-10-29)
- [x] Second llama-server for the agent model (`agent-llm`; run on an H100, the 20 GB sizes were out of stock)
- [x] Task set: about 30 field-analysis tasks based on the kobo-mcp README example prompts, plus a runner that scores tool-call success and time (Gemma 26B-A4B 22/30, gpt-oss-120b 24/30; see STATUS.md)
- [x] gpt-oss-120b run (on an H100 80 GB instead)
- [ ] Offline hardening: no outbound attempts from OpenCode, OpenWork or kobo-mcp; cold boot works (OpenCode + kobo-mcp: 8/8 offline incl. a cold OpenCode start, no failed attempts logged; per-process DNS capture and OpenWork still to do)
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
- [x] Tested locally (Docker): edge routing by Host, 60 MB upload through the proxy, range requests, APK MIME type, dotfiles blocked; Kobo guide + QGIS docs build, pass `check`, and crawl clean apart from upstream's own broken links
- [x] On the droplet (2026-10-28): `library.sh build` (13 files, 5.3 GB with docs, all checksums pinned), `kobo-setup.py --reconfigure`, edge up
- [x] Through the edge: form deploy, OpenRosa submission, qual 3/3 (`e2e-nlp.py`); 42 MB audio submission downloaded back byte-identical; KPI login and Enketo online/offline links 200; APK MIME type and resumable downloads from outside
- [ ] `offline.sh on`, then `library.sh check` and load every guide with outbound blocked
- [ ] Wi-Fi hotspot + dnsmasq for `kobo.local`/`*.kobo.local` (physical box or a spare laptop with a USB Wi-Fi dongle); install the APKs on a real Android phone over HTTP
- [ ] Landing page: KoboCollect configuration QR code and Wi-Fi QR code (per box, from firstboot)
- [ ] Content pack layout + `install.sh --pack` (debs, `docker save` images, models, library)
- [ ] Ubuntu 26.04 autoinstall USB (`CIDATA` + `KOBOPACK` partitions), LUKS + TPM
- [ ] `firstboot.sh`: per-box secrets and label card
- [ ] Second content batch: pick from the 3g candidates once pilot languages are known

### W9. Dashboards on the box (~2 weeks, after W3; see 3h)
- [ ] kobo-mcp: `DASH_SERVERS` as a setting (done: `DASH_KOBO_HOSTS`, W3); offline `desk_review` that uses `search_knowledge` (W10)
- [x] kobo-dash: trusted-host http for Kobo and tiles (or local HTTPS); `BOUNDARIES_DIR` for pre-fetched geoBoundaries; local evidence URLs (2026-10-29, kobo-dash branch `w9-offline-box`; see STATUS.md)
- [ ] Propose all of the above upstream as settings, not a fork
- [ ] Compose: box Postgres, kobo-dash web + worker, kobo-mcp in HTTP + OAuth mode; edge routes for `dash.` and `mcp.kobo.local` (SSE unbuffered); per-box keys in `firstboot.sh`
- [ ] Content pack: raster MBTiles and ADM0–2 boundaries for the deployment countries; prebuilt images
- [ ] OpenCode as an OAuth MCP client of the box's kobo-mcp, offline
- [ ] User script creates each owner's view-only `_dash` account
- [ ] ~10 dashboard tasks in W4's task set (layout from a form, shaded map, combine two projects, a story); score on 26B-A4B and gpt-oss-120b
- [ ] `offline.sh on`: create, view, live-update and share a dashboard with no outbound traffic

### W10. Local knowledge base (~2–3 weeks; can start now, see 3i)
- [ ] `remote/knowledge/`: indexer (support-bot chunker), pgvector + FTS schema, search API, MCP server
- [ ] Embedding (bge-m3) and reranker llama-servers in `docker-compose.ai.yml`
- [ ] Corpus build from the library's docs plus XLSForm, ODK docs and the XForms spec; licence check per source
- [ ] Port the support bot's eval cases; measure retrieval recall@k (`retrieve_any`/`cite_any`) and answer quality with the local agent model; re-tune threshold and boosts; with and without the reranker
- [ ] `knowledge.sh add` for PDF/DOCX/ODT/HTML/Markdown; originals served by the library
- [ ] OpenCode registration and AGENTS.md instructions; injection cases pass
- [ ] Ship the prebuilt index in the content pack
- [ ] Phase 2: upload page, local FAQ, chat widget on the landing page

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
| Dashboard specs and long workflows are too hard for smaller agent models | `generate_dashboard_layout` first, small edits after; tool profiles; shorter help text; measure in W4/W9 |
| Knowledge answers go stale, or cite a page the user can't open | Index the library's own copies; show the build date in answers' sources; refresh with the content pack |
| Documents added to the knowledge base carry personal data or injected instructions | Box-wide by design, so a "no personal data" rule for collections; retrieved text marked as untrusted; deletes denied, writes ask |
| Offline basemaps and boundaries only cover what was loaded | Choose regions with the partner before deployment; shapes and points still draw with no basemap |

## 7. Open questions

- Multi-user OpenCode: one instance per user, or a shared server with workspaces? How is a user's Kobo token passed into their MCP session?
- Which 3–6 languages for the pilot? This drives the transcription and translation evaluation and any fine-tuning (e.g. Padauk for Burmese).
- Does Kobo want to publish multi-arch (ARM) images upstream? That would reopen Raspberry Pi, Jetson and Mac for no-AI kits.
- HTTP vs local HTTPS on the box. Affects Enketo offline mode, kobo-mcp, and secure cookies, and now kobo-dash too (Kobo URL, tile origin, evidence URLs). Three apps that insist on https tilts this toward a box CA.
- Licences for redistributing the knowledge corpus on kits: Kobo Academy, the ODK docs, a forum snapshot.
- One MCP server for the agent or two (kobo-mcp plus kobo-knowledge)? Two is planned; merge only if OpenCode's per-server overhead matters.
