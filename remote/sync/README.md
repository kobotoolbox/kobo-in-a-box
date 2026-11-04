# Sync with kobo-transfer (rig tests)

Tests of the concept note's "Networked" mode (field kits → hub) with
[kobo-transfer](https://github.com/kobotoolbox/kobo-transfer). On a box, syncing is
`box/sync.py` (box README, "Syncing to a hub"); the user guide is `site/sync.html`.
Results: `../results/NOTES.md` (2026-11-04).

| File | What |
|---|---|
| `e2e-sync.py` | on a box: `seed` the test form and submissions (`--ai`: transcript, translation, qual; `--no-media` to fill a hub fast), `share` it with the box's `sync` account (`--role kit` or `hub`), `edit` submissions as Enketo does, `review` the AI results; `check` a kit's manifest against the hub's copy |
| `push.sh` | the first round: a rig pushes straight with kobo-transfer through a port forward (before boxes had names and `sync.py`) |

Two changes make syncing work; neither is upstream yet:

- **kobo-transfer**, branch `supplement-api` (`~/code/kobo-transfer`, from `1ae7a04`): AI
  results through KPI's advanced-features and supplement API instead of the removed
  `advanced_submission_post`; each source's features merged into the destination's;
  statuses and analysis synced even with no new submissions; edits sent as edits
  (`deprecatedID` set to the destination's version; changed on both sides: not sent,
  counted); absolute URLs from the server followed through the configured address;
  `--summary-file`; an error exit when anything failed.
- **KPI**, `POST /api/v2/assets/<uid>/data/<uuid>/supplement/import/`
  (`kobo/apps/subsequences/supplement_import.py`, branch `local-nlp-backend`; in the box
  backport as `supplement_import.py` + `router_api_v2.py`): another server's analysis
  versions stored as they are. kobo-transfer uses it where it exists (a GET is 405 there,
  404 elsewhere); elsewhere it copies reviewed results as manual entries.

## Boxes from a content pack (the second round)

A rig restored from the snapshot builds the pack (`box/pack.sh build`, with kobo-transfer
from `/root/kobo-transfer`); fresh Ubuntu droplets, offline from the start but for the
VPC, take it (`install.sh --pack … --first-boot-now`): each gets its name, its `sync`
account and key, the timer. Then, on each box, as the e2e user (`kobo-account.py e2e
/root/e2e-token`, not a superuser):

```bash
python3 -I e2e-sync.py seed --site X --n 0 --no-manifest && python3 -I e2e-sync.py share --role hub   # hub
python3 -I e2e-sync.py seed --site A --n 5 --ai && python3 -I e2e-sync.py share --role kit          # kit
ssh <hub> cat /etc/kobo-box/sync.token | python3 -I ../box/sync.py hub <hub address> -              # kit: pair
systemctl start kobo-box-sync   # or wait for the timer (every 5 minutes)
python3 -I e2e-sync.py --kf http://<hub address> check ../results/sync-manifest-A.json
```

The kit reads the hub's key from the hub over the VPC (as a person reads the hub's label
card): it never passes through the laptop. Droplets reach each other on 22 and 80 only
from each other's private addresses.

## Rigs restored from the snapshot (the first round)

```bash
for n in site-a site-b hub; do
  NAME=kobo-box-$n RESTORE_FROM=kobo-box-ai-snapshot SIZE=s-8vcpu-32gb-amd REGION=ams3 \
    ./provision.sh --from-snapshot
done
```

The rigs were clones, so the e2e user's token was the same everywhere, and every rig was
`kf.kobo.local`: `push.sh` reached the hub through a socat forward on
`kf.kobo.local:8090`, with `/etc/hosts` entries for the box's own names. Offline:
`NAME=kobo-box-<n> OFFLINE_KEEP=10.110.0.0/20 ./offline.sh on` for each.
