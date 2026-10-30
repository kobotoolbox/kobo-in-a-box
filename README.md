# Kobo-in-a-box AI: DigitalOcean test rig

Simulates the field laptop on a DigitalOcean droplet: the KoboToolbox stack plus local
open-weight inference (Gemma 4 for translation and qual analysis, Whisper for
transcription), with outbound internet blocked at the firewall. Use it to choose models
and hardware before buying anything.

Use test data only. This is a cloud VM, not a field device.

See [PLAN.md](PLAN.md) for the overall plan: hardware choice, KPI changes, and
OpenCode/OpenWork agents with kobo-mcp. [STATUS.md](STATUS.md) tracks where the work
stands and the next steps. [docs/concept-note.md](docs/concept-note.md) is the
non-technical overview for partners and donors.

## Layout

```
config.env          droplet size/region/image; NAME, SIZE and SSH_PORT can be overridden per run
provision.sh        create droplet + firewall (online), copy remote/ to it   ← starts billing
offline.sh on|off   block/restore all outbound traffic (simulated field conditions);
                    OFFLINE_KEEP=<cidr> keeps the VPC reachable (a model on another droplet)
park.sh             snapshot + destroy (powered-off droplets are still billed)
remote/
  bootstrap.sh          on droplet: Docker (+ Compose), NVIDIA toolkit, kobo-install, images, weights
  kobo-setup.py         on droplet: kobo-install answered for a field laptop (HTTP, kobo.local,
                        behind the edge nginx)
  ai.env                which models, thinking on/off, GPU layers, threads, memory caps
  ai.sh up gpu|cpu      start llama.cpp + whisper.cpp on the kobo-docker network
  docker-compose.ai.yml
  smoke-test.py         transcription / translation / qual benchmark using KPI's prompts
  gpu-tiers.sh          the GPU tier recipes below, one after another, with VRAM per run
  eval/fleurs-*.tsv     reference clips (transcript + English) fetched by bootstrap.sh
  e2e-nlp.py            KPI's automatic qual, translation and transcription through its real API
  kpi-test.sh           KPI's test suite against a KPI branch, set up like KPI's CI
  results/              JSON per run, for comparing tiers; NOTES.md maps runs to settings
  agents/               W4: agent model, kobo-mcp and OpenCode; test data, 30 tasks, runner
                        (agents/README.md)
  espocrm/              W11 (optional): EspoCRM case management at cases.kobo.local, and a
                        bridge that opens cases from Kobo submissions (espocrm/README.md)
  box/                  W12: what makes it a kit that runs itself (box/README.md): fixed
                        internal address, AI tier from the hardware, KOBOBACKUP drive backups
  library/
    manifest.tsv        installers and docs served at http://kobo.local (pinned versions, SHA-256)
    library.sh          build (fetch + docs + render) | check | up|down|logs (edge nginx on :80)
    render.py           landing page from the manifest and what's on disk
    nginx/edge.conf     kf/kc/ee.* → Kobo on :8080; cases.* → EspoCRM on :8084;
                        everything else → /srv/library
```

## Workflow

```bash
# 1. Create (asks before billing starts). Overrides, e.g.:
#   SIZE=s-8vcpu-32gb-amd   CPU only (also the default GPU sizes are often out of stock)
#   NAME=kobo-box-gpu       a second rig with its own firewall and snapshot
#   SSH_PORT=443            if your network blocks outgoing port 22 (then ssh -p 443 …)
./provision.sh
ssh root@<ip> 'bash /root/kobo-box-ai/bootstrap.sh'      # ~25GB of downloads

# 2. Install Kobo like on the laptop (non-interactive, ~15 min)
ssh root@<ip> 'python3 -I /root/kobo-box-ai/kobo-setup.py'
#   Production mode over plain HTTP, with kf/kc/ee.kobo.local mapped to the droplet IP
#   inside the containers. Kobo's nginx listens on 8080; kobo-setup.py also starts the
#   edge nginx on port 80 (library/library.sh up), which kobo-install needs to see Kobo.
#   Prints the super_admin password at the end (also in /root/kobo-install/.run.conf).
#   Then point those hostnames at the droplet IP in /etc/hosts on your machine/phone
#   (the box's own DNS does this in the field):
#     <ip>  kobo.local kf.kobo.local kc.kobo.local ee.kobo.local
#   Afterwards manage it with run.py as usual (--stop, --logs, --setup).
#   An install from before the edge proxy: kobo-setup.py --reconfigure moves it to 8080

# 2b. Offline library + edge nginx on port 80 (~4GB of downloads)
ssh root@<ip> '/root/kobo-box-ai/library/library.sh build'   # pin any UNPINNED checksums it prints
ssh root@<ip> '/root/kobo-box-ai/library/library.sh up'
#   http://kobo.local: landing page with installers and guides; http://kf.kobo.local: Kobo

# 3. Start inference and test while online
cd /root/kobo-box-ai && ./ai.sh up gpu
python3 -I smoke-test.py

# 4. Go offline (from your machine) and repeat. Everything should still pass,
#    and the egress check should say OFFLINE
./offline.sh on
ssh root@<ip> 'cd /root/kobo-box-ai && python3 -I smoke-test.py'

# 5. Done for the day
./offline.sh off   # optional; provision.sh re-opens it anyway
./park.sh
# later: set REGION in config.env to the snapshot's region, then
./provision.sh --from-snapshot
# Only for snapshots before W12's fixed address (BOX_IP): make Kobo follow the new IP
ssh root@<new-ip> 'cd /root/kobo-install && python3 run.py'
ssh root@<new-ip> '/root/kobo-box-ai/library/library.sh up'

# KPI with local AI (W2): run the KPI branch's tests, and the end-to-end check through
# KPI's API (needs KPI running NLP_BACKEND=local; see STATUS.md)
ssh root@<ip> 'bash /root/kobo-box-ai/kpi-test.sh'
ssh root@<ip> 'python3 -I /root/kobo-box-ai/e2e-nlp.py e2e "$(cat /root/e2e-user.pw)"'

# Agents (W4): see remote/agents/README.md for the two-droplet session

# The box (W12): fixed internal address + backup units, AI tier from the hardware,
# and Kobo bound to the fixed address (see remote/box/README.md)
ssh root@<ip> '/root/kobo-box-ai/box/box.sh install && apt-get install -y restic'
ssh root@<ip> 'cd /root/kobo-box-ai && BOX_IP=10.254.254.254 python3 -I kobo-setup.py --reconfigure'
ssh root@<ip> 'cd /root/kobo-box-ai && python3 -I box/detect-tier.py && ./ai.sh up auto'
ssh root@<ip> '/root/kobo-box-ai/box/backup.sh run /var/backups/kobo-box'   # or plug in KOBOBACKUP

# Case management (W11, optional): EspoCRM + the Kobo bridge, then the end-to-end check
ssh root@<ip> '/root/kobo-box-ai/espocrm/espocrm.sh up --demo-users'
ssh root@<ip> 'python3 -I /root/kobo-box-ai/espocrm/e2e-espo.py --edge'
```

Add real test clips (any format ffmpeg reads) to `/opt/models/audio/` on the droplet.
Ideally use 1–5 minute interviews in each target language. The bundled `jfk.wav`
is only an 11-second sanity check.

## Simulating laptop tiers on one GPU droplet

Edit `remote/ai.env`, then `./ai.sh up …`. Each run's JSON records the model, timings,
and GPU power, so tiers can be compared.

| Target hardware | `ai.sh up` | ai.env changes | VRAM measured (with whisper turbo) |
|---|---|---|---|
| CPU-only laptop, 32GB, 4 cores | `cpu` | `LLM_THREADS=4 WHISPER_THREADS=4 AI_CPUS=4 AI_MEM_LIMIT=24g`, `WHISPER_MODEL=ggml-medium-q5_0.bin` | — |
| Laptop with 8GB GPU (RTX 4060) | `gpu` | E4B Q4_0 + whisper turbo | 6.3 GB: fits |
| Bigger LLM on 8GB GPU (partial offload) | `gpu` | `LLM_MODEL=gemma-4-26B-A4B-it-Q4_0.gguf LLM_MMPROJ= LLM_NGL=12` | 8.6 GB: just over; use fewer layers or whisper on the CPU |
| Field server / 20GB+ GPU | `gpu` | `LLM_MODEL=gemma-4-26B-A4B-it-Q4_0.gguf LLM_MMPROJ=` | 17.5 GB: fits |
| 80 GB GPU / 128 GB unified memory | `gpu` | `LLM_MODEL=gpt-oss-120b-MXFP4.gguf LLM_MMPROJ= AI_MEM_LIMIT=200g` | 62.8 GB |

`remote/gpu-tiers.sh` runs all of them. The 20–48 GB GPU sizes have been out of stock, so
the 2026-10-29 runs used an H100 (`gpu-h100x1-80gb`): VRAM is what each tier needs, but
timings are far faster than a laptop GPU. CPU-tier results are more representative because
thread count is capped.

**Power:** `gpu_power.gpu_wh` in the results is GPU-only energy for the run. For a
field-laptop estimate, add roughly 20–40W for the rest of the system over the same time.

## What the smoke test proves

- **Qual analysis** uses KPI's real prompt templates and the same strict
  `TRUE,FALSE,…` regex parser as `kobo/apps/subsequences/prompts.py` on kpi main.
  `PARSE FAIL` means KPI would reject that model's answer, so the prompt or parser
  needs adapting for that model.
- **Translation** covers fr/es/sw/pt sample sentences. Replace them with your target
  languages and have a speaker judge the results.
- **Scored clips.** Clips listed in `eval/*.tsv` get a word error rate (WER) against
  the reference transcript, and a chrF score (0–100) for the English translation,
  both from the reference text (`mt_chrf`, translation alone) and from Whisper's
  output (`pipeline_chrf`, what KPI would produce). `eval/fleurs-es_419.tsv` has 16
  [FLEURS](https://huggingface.co/datasets/google/fleurs) Spanish clips on health,
  water, food, disasters and children, 8 female and 8 male speakers. Add a language
  by adding `eval/fleurs-<config>.tsv` with the same columns. FLEURS is clean read
  speech, so treat these scores as a best case; numbers written as digits vs words
  also count as WER errors.
- **Thinking mode** is off by default (`LLM_THINKING=false`). With it on, Gemma 4
  spends 200–500 hidden tokens per call; with `--reasoning-budget 0` instead, the
  reasoning leaks into the answer and every qual case is a `PARSE FAIL`.
- **Gemma audio** runs only if `LLM_MMPROJ` is set. It tests Gemma as the
  transcription model (clips are capped at 30s), compared with Whisper.

## Not covered here

- Local Wi-Fi, DNS for `*.kobo.local`, phones joining over the LAN and installing APKs
  from the library (proven on the v0.1 laptop and in Jamaica; to retest on the box, PLAN W8)
- Laptop thermals, sustained-load throttling, real battery life
- **KPI's language tables** for the pilot languages, and a KPI image built from the branch.
  The KPI changes themselves (`NLP_BACKEND=local`: qual, translation and transcription on
  the local models, same action IDs) are on the `local-nlp-backend` branch and tested
  (STATUS.md, W2); the running Kobo on the rig uses a backport mounted into the release.
- **Multi-user agents:** the agent tests use one Kobo account through kobo-mcp's header
  mode; OAuth sign-in and one OpenCode per user are still to test (PLAN W4).

## Cost

| Size | $/h | Typical use |
|---|---|---|
| `gpu-4000adax1-20gb` | 0.76 | default; all tiers except 31B dense |
| `gpu-6000adax1-48gb` | 1.57 | only for testing 31B / the field-server tier |
| `s-8vcpu-32gb-amd` | 0.25 | Kobo-only work / KPI branch development; the agent rig's Kobo side |
| `gpu-h100x1-80gb` | 4.41 | what was in stock: the GPU tiers and the agent model (gpt-oss-120b fits). Delete it after the session rather than parking it (the models download again in minutes) |

Park the droplet when not in use. Snapshots cost about $0.06/GB/month.
