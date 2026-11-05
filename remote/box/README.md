# The box: from a factory USB to a kit that runs itself (W12)

Goal: a non-technical team receives a kit, switches it on, scans the Wi-Fi QR code on the
label card and opens `kobo.local`. Nobody installs, configures or types a command, in the
field or before. PLAN section 3k has the reasoning; this folder holds the pieces as they
are built.

## The approach: preinstalled boxes, a USB stick for the factory

```
 build machine (online)          factory USB (KOBOPACK)             box, first power-on
 ───────────────────────         ──────────────────────             ──────────────────────
 library.sh build                Ubuntu autoinstall          ──▶    firstboot.sh: own secrets,
 docker save images      ──▶     + content pack              ──▶    Wi-Fi, label card
 model weights                   + install.sh --pack                services start on boot
 .debs (restic, dnsmasq…)        (one stick, many boxes)            detect-tier → ai.box.env
```

- **Boxes ship preinstalled.** Whoever prepares kits (Kobo, a partner's IT, a supplier)
  boots each new machine from the factory USB once. Autoinstall wipes the disk, installs
  Ubuntu with an encrypted disk that the TPM unlocks, and runs `install.sh` from the content
  pack. Nothing is downloaded. The same stick reinstalls a box that breaks in the field.
- **Every box gets its own secrets at first power-on** (`firstboot.sh`), never at the
  factory, so two kits never share passwords or keys. This is why a disk image isn't
  cloned.
- **The box adapts to its hardware** instead of being configured for it:
  `detect-tier.py` picks the AI settings, and the fixed internal address (`box.sh`) means
  Kobo doesn't care which network the box is on.
- **Running live from the USB stick isn't supported:** the models alone are 5–65 GB, and
  databases on a USB stick are slow and wear it out. The stick installs; the box runs.

## What is here

| Piece | What it does | State |
|---|---|---|
| `box.sh ip up` | Fixed internal address `10.254.254.254` on a dummy interface; `BOX_IP=… kobo-setup.py` binds Kobo to it | Built; tested on the rig |
| `backup.sh` | Encrypted, deduplicated backups (restic) of Kobo's databases, media and settings, and EspoCRM's; `restore` onto the same or a new box | Built; tested on the rig, offline too, and restored onto a fresh box |
| `box.sh install` | systemd: the address at boot; a nightly backup to the box's disk; **a full backup whenever a drive labelled `KOBOBACKUP` is plugged in**, then it unmounts itself | Built; tested on the rig |
| `detect-tier.py` | RAM, cores and GPU → `ai.box.env`; `./ai.sh up auto` | Built; tested on the rig (CPU) |
| `pack.sh build <dir>` | The content pack: debs, images, models, library, pinned kobo-install/kobo-docker, all checksummed | Built; 30 GB from the rig |
| `install.sh --pack <dir>` | Offline install from the content pack | Built; tested on a fresh droplet offline from the start |
| `firstboot.sh`, `card.py` | First power-on: name, Kobo and its passwords, backup passphrase, Wi-Fi details, case management, AI, label card | Built; tested on a factory-installed droplet |
| `kobo-account.py` | A Kobo account for one of the box's services (the case bridge's `cases-bridge`) and its token | Built; tested |
| `update.sh --pack <dir>`, `box.sh update-drive` | Update a box in use from a newer pack, keeping its data and passwords; by itself when a signed `KOBOPACK` stick is plugged in | Built; tested 37c → 37d offline |
| `watchdog.sh` | Restarts a model server that stops answering its healthcheck (every minute, before the status page) | Built; tested on the rig |
| `status.py` | Status page at `kobo.local/status`: Kobo, AI, disk, backups, battery in plain words; every minute | Built |
| `sync.py` | A field kit syncs its projects to its hub by itself (kobo-transfer), every 5 minutes when connected; pairing, status page row | Built; tested on fresh boxes from a pack (below) |
| Autoinstall USB | Ubuntu 26.04 ISO + `CIDATA` + `KOBOPACK` partitions, LUKS + TPM | Needs the W5 box |

## Backups

```bash
box/backup.sh run /media/kobobackup     # full: databases, media, settings
box/backup.sh run /var/backups/kobo-box --no-media
box/backup.sh list /media/kobobackup
box/backup.sh restore /media/kobobackup [snapshot]   # same box or a freshly installed one
box/backup.sh status                    # last result, as JSON (for the status page)
```

- **For the focal point:** plug in the backup stick (any USB drive formatted with the label
  `KOBOBACKUP`), wait for the status page to say it's done, unplug it, keep it somewhere
  else than the box. Weekly, or after each big collection day.
- **Encrypted** with the box's backup passphrase (`/etc/kobo-box/backup.pass`, made by
  `firstboot.sh` and printed on the label card; on rigs without it, made on first use). Keep the card away from
  the box: without the passphrase a backup can't be restored, and with it anyone holding
  the stick can read it.
- **Incremental:** restic only stores what changed, so weekly backups of a large project
  with audio stay fast, and keep 7 daily, 8 weekly and 12 monthly versions.
- **What's in it:** Kobo's Postgres (KPI and KoboCAT databases) and Mongo as dumps taken
  while Kobo runs; KoboCAT and KPI media (attachments, audio); kobo-install's settings and
  `kobo-env` (passwords, Django secret); EspoCRM's database, files and secrets if it's
  installed. Not included, because the content pack restores them: the library, model
  weights, Docker images. Not yet: OpenCode's session history (W4 decides where it lives).
- **Restore** first takes a safety backup of the current databases and settings (to
  `/var/lib/kobo-box/before-restore`), so a restore can itself be undone. Then it stops
  Kobo's front end, replaces the databases with the backup's, adds the backup's media
  (files collected since stay), and starts Kobo again. On the same box that's all
  (47 s on the rig).
- **On a replacement box:** install it from the factory USB, plug in the backup drive,
  `backup.sh restore /media/kobobackup`, and type the old box's passphrase from its label
  card. The new box keeps its own install settings and takes only the accounts and secrets
  (passwords, Django secret, Enketo keys) from the backup, since the databases need them.
  Postgres's and Mongo's passwords are set to the restored ones (dumps don't carry them;
  Mongo's user collections are skipped, because replacing them mid-restore drops the
  restore's own login), then `kobo-setup.py --reconfigure` re-renders Kobo's settings.
  109 s on a fresh droplet. EspoCRM comes back too: when the backup is another box's,
  `espocrm.sh restore` gives this box's MariaDB users the backup's passwords and takes its
  secrets file (EspoCRM's config and database expect them), and recreates the containers.
  The case bridge's token file is rewritten from the restored Kobo database
  (`kobo-account.py`), and the label card from the restored passwords.

## Status page

`http://kobo.local/status/`, linked from the landing page: one coloured line saying whether
everything works, then one row per part in plain words, with what to do when it's not green.

```bash
python3 -I box/status.py           # write status/index.html and status.json into the library
python3 -I box/status.py --print   # the same checks in the terminal (support over SSH)
```

- **What it checks:** KoboToolbox (KPI's `/service_health/` and Enketo through Kobo's nginx,
  and every Kobo container running); the AI models (llama-server's `/health`: loading or
  ready; whisper-server); the assistant and case management if they're installed; the edge;
  free disk space; backups; the battery where there is one.
- **Backups, as the focal point sees them:** "Backing up to the drive now. Don't unplug it"
  while the drive unit runs; "finished at 14:02, you can unplug the drive" for an hour after;
  a warning after 7 days with no drive backup, or 36 hours with no nightly copy; red with the
  reason when the last backup failed.
- **Starting up isn't an error:** for 15 minutes after boot, a part that isn't up yet shows as
  "starting" (blue), not red.
- **Static, and refreshed every minute** by `kobo-box-status.timer` (`box.sh install`), and by
  `backup.sh` when a backup starts and ends. The edge serves it like the rest of the library,
  so nothing reachable from the Wi-Fi can talk to Docker. It refreshes itself in the browser
  every 30 s, and says so if it's more than 5 minutes off the phone's clock: either the checks
  stopped, or the box's clock is wrong (which would also put wrong times on submissions).
- **A hung model server restarts by itself.** llama-server and whisper-server have Docker
  healthchecks (`/health`, `/`; 4 misses 30 s apart, after a start period for loading), and
  `watchdog.sh` restarts a container labelled `kobo-box.watchdog=restart` once Docker marks
  it unhealthy, at most 3 times an hour; Docker alone only restarts a process that exits.
  `/health` is answered outside the inference loop, so a long transcription isn't a hang.
  The page then says "It stopped answering and was restarted automatically at 16:53" for a
  day. Tested on the rig by freezing whisper-server (`kill -STOP`): restarted on the first
  status run after Docker marked it unhealthy, then green.
- **Not yet:** temperature (needs the W5 box's sensors), translations of the page.

## Syncing to a hub

A field kit sends its projects to a hub kit at base, by itself, whenever it can reach it
(`sync.py`, with kobo-transfer; the user guide is `site/sync.html`, the rig test
`../sync/README.md`).

```bash
box/sync.py hub 192.168.8.20 -      # once, on the field kit: the hub's address, and its sync
                                    # key (on the hub's label card) on stdin
box/sync.py projects                # which projects sync where, and why others don't
box/sync.py run                     # now; the timer runs `run --if-connected` every 5 minutes
box/sync.py status                  # the last run, as JSON (the status page reads it)
box/sync.py resolve <uuid> --keep here|hub   # a submission edited on both kits: which wins
box/sync.py hub --forget
```

- **Every box has a Kobo account `sync`** (first boot, `kobo-account.py`), not a superuser,
  no password; its key is on the label card. It sees only the projects shared with it, so
  a project syncs only when staff share it, on both kits: on the field kit with "View
  submissions", on the hub with "View", "Add", "Edit" and "Validate submissions". Projects
  are matched by name, so the hub's copy of a form is deployed from the same XLSForm.
- **Kits address each other by name.** Every box's Kobo also answers to `kf.<box name>.local`
  and `kc.<box name>.local`: the edge maps any `kf.*`/`kc.*`/`ee.*` host to Kobo's own names,
  and rewrites redirects back to the name used (`library/nginx/edge.conf`). `box.sh ip up`
  puts the box's own names in `/etc/hosts` (at every boot); pairing asks the hub's address
  which box it is (`/box.json`, written by `library/render.py`) and adds `kf/kc.<hub>.local`
  for that address. The hub's `kobo.local` names are never used: on a kit they mean that kit.
- **The timer** (`kobo-box-sync.timer`, every 5 minutes on the clock, only with
  `/etc/kobo-box/sync.env`) does nothing when the hub doesn't answer on port 80, so plugging
  the cable in is all it takes. Each matched project runs kobo-transfer with
  `--sync --validation-statuses --analysis-data --summary-file`, in
  `/var/lib/kobo-box/sync/<project>/` (its settings with both keys, owner-only; the last
  run's log; what it last sent, for edits).
- **Edits.** A submission edited on the kit after it was sent goes to the hub as an edit of
  the hub's copy (kobo-transfer sets `deprecatedID` to the hub's version), instead of being
  refused there as a duplicate root UUID. A copy changed on the hub (a correction there) is
  kept; one changed on both sides isn't sent, and the status page says so until support
  chooses (`resolve`: `--keep here` records the hub's version as the one last sent, so the
  next sync sends ours as its edit; `--keep hub` records ours, so it's left).
- **Status page:** nothing on a box that isn't paired (a hub); "Syncing to the hub … now";
  "Synced to the hub … 3 minutes ago: 12 new submissions"; when the hub isn't connected,
  when it was last synced (a warning after 3 days); what's wrong in plain words: a project
  the hub doesn't have, the hub's `sync` account missing a permission (403s), edits on both
  sides, a key the hub no longer accepts.
- **Backups and updates:** `/etc/kobo-box` is in the backups, so the pairing is too; a
  restore onto a kit that isn't paired takes it (tested: 57 s, then syncing on), the next
  run puts the hub's name back in `/etc/hosts`, and the `sync` account's token file follows
  the restored database. `update.sh` copies the pack's kobo-transfer, and a box set up
  before syncing existed gets its `sync` account from `firstboot.sh catch-up` (below).

## Next steps (in order)

1. ~~Status page~~: built (above).
2. ~~Content pack + `install.sh --pack`~~: built (below).
3. ~~`firstboot.sh`~~: built (below), with case management. Still to add: the dashboards'
   keys when they're part of the kit, the assistant (below), the LUKS key (with the
   autoinstall).
4. **Hotspot + local DNS** (NetworkManager shared mode + dnsmasq for `*.kobo.local`) and
   the KoboCollect QR code on the landing page. Needs the physical box; check its Wi-Fi
   chip supports access-point mode, or ship a known-good USB Wi-Fi adapter.
5. **Autoinstall USB with LUKS + TPM** on the W5 box.
6. **Power:** shut down cleanly when the battery is low (laptop form factor), so the
   databases are never cut off mid-write.
7. ~~Updating a kit from a newer content pack without losing data~~: built (below).
   ~~Sync to a hub~~: built (above). **Later:** to a cloud Kobo (concept note, "Connected"):
   the same kobo-transfer run with the server's addresses; and finding the hub on a cable
   with no DHCP (mDNS, on the W5 box).

## Content pack

The factory USB's content: everything a box needs, so a box is set up with no internet.
Built from a working box or rig, so it holds what was tested there, not a fresh download.

```bash
box/pack.sh keygen                    # once: the signing key, /root/kobo-pack-signing.key
box/pack.sh build /media/kobopack     # online, as root; incremental (unchanged images kept); signed
box/pack.sh verify /media/kobopack [--key signing.pub]
/media/kobopack/kobo-box-ai/box/install.sh --pack /media/kobopack   # on the new box, offline
```

```
KOBOPACK/
  pack.json        version, build date and host, OS, kobo-install version, images, models, sizes
  SHA256SUMS       every file; install.sh checks them all before touching the box
  SIGNATURE        ed25519 signature of SHA256SUMS + pack.json (pack.sh keygen); signing.pub
  debs/            212 packages (Docker, restic, git, jq, zstd, exfatprogs, rsync…) and every
                   dependency, as a local apt repository, for one Ubuntu release (24.04 now)
  images/          docker save of every image the box's containers run (14, 4.9 GB with zstd)
  models/          /opt/models: Gemma 4 E4B and 26B-A4B, Whisper turbo and medium, test audio
  library/         /srv/library
  kobo-box-ai/     this repo's remote/ (no results, no per-box files)
  kobo-install/    git checkouts at the running commits (2.026.37d)
  kobo-docker/
  kpi-e2e/         the KPI local-AI backport (STATUS W2), mounted by kobo-setup.py; KPI_IMAGE
                   names the KPI release its files are from, and pack.sh refuses any other
  kobo-transfer/   for syncing (sync.py), with VERSION; never its settings, logs or downloads
```

- **Never in the pack:** kobo-install's `.run.conf` and `kobo-env` (passwords), Kobo's data,
  backups, the backup passphrase, EspoCRM's secrets, OpenCode's generated config.
- **14 minutes** on an 8-vCPU droplet: checking the pack 2.5, debs 1, loading images 4,
  copying files 2, Kobo's first start 4.5; then all green on the status page and
  `e2e-nlp.py` PASS, with outbound traffic blocked from before the pack was attached.
- **`install.sh` is the factory step**: checks the pack, installs the debs from the pack only
  (its own apt lists, so a stuck system `apt-get update` can't block it) and turns off
  Ubuntu's daily apt runs, loads the images, copies the files, sets up `box.sh` (address,
  units), the library and the status page, and enables `kobo-box-firstboot.service`. Then it
  stops: no passwords exist yet, so every box from one pack is identical (11 min).
  `--first-boot-now` runs first boot straight away (rigs). A failure names the step.
- **Signed.** With `/root/kobo-pack-signing.key` (`pack.sh keygen`) the pack is signed, and
  `install.sh` keeps its public key in `/etc/kobo-box/pack-signing.pub`: the key update
  sticks must be signed with. Keep the private key off packs and boxes (and a copy safe:
  without it, boxes in the field can only be updated over SSH). `verify` also fails on
  any file in the pack's folders that `SHA256SUMS` doesn't list, since `sha256sum -c` only
  checks what's listed (it found the library's own `SHA256SUMS` missing from the list).

## Updating a box

A box in use takes a newer pack without losing anything: plug the stick in (or run
`update.sh` over SSH). Whoever makes packs updates the rig first, tests it, then builds:

```bash
# On the rig, online: e.g. a new Kobo release
./kpi-backport-rebase.sh kobotoolbox/kpi:2.026.37d      # the backport's files, 3-way merged
for r in kobo-install kobo-docker; do git -C /root/$r fetch --tags && git -C /root/$r checkout 2.026.37d; done
BOX_IP=10.254.254.254 python3 -I kobo-setup.py --reconfigure
python3 -I e2e-nlp.py e2e <password>; python3 -I espocrm/e2e-espo.py --edge
box/pack.sh build /media/kobopack                       # signed

# On the box: plug the stick in (box.sh update-drive), or
/media/kobopack/kobo-box-ai/box/update.sh --pack /media/kobopack
```

- **Plugging in a `KOBOPACK` stick** on a box that is set up runs `box.sh update-drive`: the
  box's own `pack.sh` checks the signature against `/etc/kobo-box/pack-signing.pub` and that
  nothing on the stick is unlisted, before anything from the stick runs; then the stick's
  `update.sh` (newer than the box's). A stick that fails is unmounted, nothing changes, and
  the status page says "The update stick was not used". At the factory the same rule does
  nothing (`ConditionPathExists=/etc/kobo-box/firstboot-done`). An unsigned pack only
  updates over SSH. Not covered: a stick whose firmware changes its contents after the check.
- **`update.sh`, in order:** checks (the pack; newer than the box's `pack.json` unless
  `--force`; no local changes in kobo-install/kobo-docker; the backport matches the pack's
  KPI), a databases-and-settings backup to `/var/backups/kobo-box`, the debs, new images,
  the files (keeping `ai.box.env`, `*.local.env`, `results/`, the library's status page,
  card and service links), kobo-install and kobo-docker at the pack's commits and, if they
  or the backport changed, `kobo-setup.py --reconfigure` (passwords kept; KPI migrates its
  databases on start), `box.sh install`, then the edge, the AI and case management started
  again on the new files (dashboards, paper forms and the knowledge base too); last,
  `firstboot.sh catch-up`: whatever a new box gets at first power-on that this one doesn't
  have yet (case management, dashboards, paper forms, `sync`, the knowledge base, each when
  the pack has it), then the label card again. A part counts as there by its per-box file
  (`/etc/kobo-box/paper.env`, `sync.token`...), not by first boot's record, since a pack
  without a part's images recorded its step as done. The assistant isn't updated yet.
- **Status page:** "Updating this kit. Leave it switched on" with the step, then "Updated at
  19:28… You can remove the update stick" for a day, or what failed with "plug the update
  stick in again: the update carries on". The box's `pack.json` only changes at the end,
  so a re-run (or a power cut) carries on; each step is safe to repeat.
- **Tested** (2026-11-02, offline throughout): a box installed from a 37c pack, with a form,
  13 submissions and 10 cases; the rig moved to 37d (backport rebased cleanly, `e2e-nlp.py`
  PASS, `e2e-espo.py` 27/27) and a 37d pack built. Attaching it to the box started the
  update by itself. The first try stopped at the Kobo step (a tag from the 37c pack clashed
  with the 37d pack's: fetches now take the pack's tags) and the page said so in red; the
  fixed stick, plugged in again, carried on and finished in 4 min (Kobo down ~80 s): KPI
  2.026.37d with 37d's SVG-upload fix in the mounted settings, the form, 13 submissions and
  10 cases there, all green, `e2e-nlp.py` PASS through the rebased backport. Three tampered
  sticks (an added script, a changed `pack.json`, a changed listed file) were each refused
  before anything ran.
- **Tested from an older pack** (2026-11-05, offline): a box installed from a pack of the
  3 November code (before dashboards, paper forms and syncing), with a form and 5
  submissions, took the current pack in 3½ min: catch-up set up dashboards, paper forms
  (account, password 600, card section) and the `sync` account, and the card again; the
  submissions checked out (`e2e-sync.py check`). Found: a quote in a new status-page label
  broke `status.py`, so the page stayed on "Updating this kit" and a factory install from
  that pack failed. `pack.sh build` now refuses a pack whose Python or shell scripts don't
  parse. (The old pack was built on today's rig, so it already had the newer images and KPI
  backport: this covered the new parts, not new images or a KPI change.)

## First power-on

`firstboot.sh`, run once by `kobo-box-firstboot.service`, makes the box its own. Each step is
recorded when it finishes (`/var/lib/kobo-box/firstboot.json`), so a power cut carries on
from the next step at the next boot; `/etc/kobo-box/firstboot-done` ends it.

| Step | What |
|---|---|
| name | hostname `kobo-<4 letters>` (the backup repository and the card use it); cloud images told to keep it |
| kobo | `kobo-setup.py --pinned`: Kobo from the pack's kobo-install, which makes every Kobo password and the Django secret (`--reconfigure` if a power cut came after it started) |
| secrets | backup passphrase; Wi-Fi name `Kobo-<4 letters>` and a passphrase in four groups of four, for the hotspot |
| cases | when the pack has EspoCRM's images: the Kobo account `cases-bridge` (not a superuser, no password, sees only forms shared with it) and its token (`kobo-account.py`), `/etc/kobo-box/espocrm.env` pointing the bridge at it, then `espocrm.sh up` (EspoCRM's own passwords) |
| paper | when the pack has kobo-field-forms' image: the Kobo account `paper-forms` (as `cases-bridge`) and its token, `/etc/kobo-box/paper.env` pointing paper forms at it, then `paper.sh up` (the app's own password, on the card) |
| sync | the Kobo account `sync` (as `cases-bridge`) and its token, `/etc/kobo-box/sync.token`: the key on the card that field kits pair with (`sync.py`) |
| ai | `detect-tier.py`, `./ai.sh up auto` |
| card | `card.py`: the label card |

- **The status page shows it:** "Setting up this kit for the first time, about 10 minutes.
  Now: setting up KoboToolbox", and only the library and disk rows, since nothing else exists
  yet. A failed step turns red with "restart the kit: setup carries on where it stopped".
- **The label card** (`kobo.local/card/`): the Wi-Fi name and passphrase with a QR code that
  phones join from, the Kobo admin account, EspoCRM's admin account and "share the form
  *Community health referral* with the user `cases-bridge`", the backup passphrase, the disk's recovery key
  when there is one, and "keep this apart from the kit and the backup drive". It holds the
  secrets, so the edge serves it **only to a browser on the box itself** (403 from anywhere
  else), and `pack.sh` never packs it. That suits a laptop box. How a screenless mini PC
  gets its card printed (a one-time code on the status page, a USB printer, the factory
  printing it at first power-on before shipping) is open, and goes with the hotspot step.
- **Tested** (2026-11-02, fresh droplet, offline throughout): factory install, power off, on:
  setup in 6 min, all green, `e2e-nlp.py` PASS; a drive backup with the new passphrase into
  `kobo-box-kobo-bkqf`; the card 200 on the box and 403 from outside; after another reboot
  the name was kept, setup didn't run again and everything came back by itself. The first
  attempt failed at "name" (`tr < /dev/urandom | head` under `pipefail`): the page showed
  it in red, and a restart carried on after the fix.
- **Case management, tested** (2026-11-02, a fresh droplet offline throughout): factory
  install and first boot 16.7 min in all, all green with case management; then the rig's
  backup (60 cases) restored onto it in 139 s with nothing typed: 60 cases back under the
  old box's EspoCRM password, the bridge's token valid, the card rewritten; then
  `e2e-espo.py --edge --share-with cases-bridge` 28/28: the form shared as staff would,
  10 new cases (numbered on from 61) through the bridge's own account.
- **Not in it yet:** the assistant. Its images are in the pack, but its model server only
  has a CUDA build (the recommended box is AMD, W5), and W4 hasn't decided how each user's
  Kobo token reaches their session. Also: CUDA images (`EXTRA_IMAGES=...` when building for NVIDIA boxes), a
  signature (only checksums: PLAN 3k).

Found by the offline install, all fixed:
- **KPI never starts on a box installed offline.** Its entrypoint runs `uv pip sync` against
  PyPI and GitHub whenever its container is new, unless a marker inside the container says
  it already did; offline it retries for ever. Rigs never showed it because their first
  start was online. `uv --offline` doesn't help (it wants to re-fetch the git-pinned
  packages). The image's virtualenv already matches (`uv pip freeze` identical before and
  after a sync), so `kobo-setup.py` mounts the image's own requirements.txt as the marker,
  in the `docker-compose.frontend.custom.yml` it now writes (with the backport mounts, which
  until now were a hand-placed file on the rig).
- **A fresh Ubuntu's first-boot `apt-get update` hangs offline** and holds apt's lists lock;
  so did DigitalOcean's agent installer, holding dpkg's. The pack's apt uses its own lists
  and waits up to 10 min for dpkg's lock.
