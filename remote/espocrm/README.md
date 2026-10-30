# Case management on the box (W11)

An optional EspoCRM at `http://cases.kobo.local`, for following up what Kobo forms find,
with no internet. A bridge polls Kobo and opens a case for each submission that needs
follow-up, routed to the right team. Staff work the cases in EspoCRM's own UI. The
EspoCRM side is based on the local stack Ponto tests its connector against
(`~/code/ponto/infra/espocrm`, `scripts/espocrm_bootstrap.py`), with per-box passwords
instead of fixed dev ones.

| File | What it is |
|---|---|
| `espocrm.env` | Image versions, port (127.0.0.1:8084), site URL, time zone, the template, where the bridge finds Kobo and its token |
| `docker-compose.espocrm.yml` | `db` (MariaDB), `espocrm`, `espocrm-daemon` (scheduled jobs), `bridge` (profile `bridge`) |
| `espocrm.sh` | `pull` (online), `up [--demo-users]`, `setup`, `down`, `logs`, `status`, `backup`, `restore` |
| `espocrm-setup.py` | Idempotent setup from the template: teams, roles, Case fields, layouts, the bridge's API user; version checks off |
| `bridge.py` | Kobo → EspoCRM: polls the form's submissions, opens one case per submission that needs it. Stdlib only |
| `templates/health-referral.toml` | The test scenario: which form, which submissions, how they map to case fields, which team gets what |
| `health_fixture.py` | The scenario's Kobo form (with the referral rules as calculations), 13 made-up visits and the case each should open |
| `test_bridge.py` | Unit tests with Kobo and EspoCRM faked: `python3 -m unittest test_bridge` |
| `e2e-espo.py` | End to end through the running bridge: visits in Kobo → cases, routing, permissions, no external assets |

## The test scenario: community health referrals

Made-up people and places. Community health workers (CHWs) visit households in four zones
of a displacement camp with a Kobo form. They screen children under five for the general
danger signs (unable to drink, vomiting everything, convulsions, lethargy, chest
indrawing) and for acute malnutrition (MUAC), ask about diarrhoea and dehydration, and check
pregnant women for danger signs. The form works out where to refer. Each visit that needs
a referral becomes a case:

| Referral reason | Team | Priority | Follow up within |
|---|---|---|---|
| Suspected cholera (AWD with severe dehydration, 2 years or older) | Surveillance | Urgent | 6 h |
| Child or pregnancy danger signs | Referral coordinators | Urgent | 24 h |
| Bloody or persistent diarrhoea | Referral coordinators | High | 48 h |
| Severe acute malnutrition (MUAC < 115 mm) | Nutrition (OTP) | High | 48 h |
| Moderate acute malnutrition (115–124 mm) | Nutrition (OTP) | Normal | 7 days |

A visit with several reasons goes to every matching team, at the highest priority and the
earliest follow-up. The caregiver's phone is only asked for, and so only on the case, when
they agree to be called back. Staff record the outcome (arrived and treated, admitted,
enrolled, did not arrive, refused…) and close the case.

**Roles** (`espocrm-setup.py`): *Case worker*: their teams' cases only, can't delete or
export. *Case supervisor*: all cases, no delete. *Kobo bridge*: create and read cases,
nothing else. `--demo-users` adds one case worker per team and a `supervisor`, with
passwords in the secrets file.

## Running it

```bash
# Online, once (also what goes into the content pack): ~1.6 GB of images
/root/kobo-box-ai/espocrm/espocrm.sh pull

# Needs Kobo and the edge (library.sh up) running, and a Kobo token for the bridge
/root/kobo-box-ai/espocrm/espocrm.sh up --demo-users
#   first start: generates passwords in /root/espocrm.secrets, EspoCRM installs itself
#   (~1 min), setup runs, the bridge starts, the landing page gets a "Case management" link
#   then http://cases.kobo.local, user admin, password ESPO_ADMIN_PASSWORD in the secrets file

python3 -I /root/kobo-box-ai/espocrm/e2e-espo.py --edge   # 27 checks, ~2 min
```

To try the EspoCRM side on a laptop (no Kobo): put overrides in `espocrm.local.env` (not
in git), e.g. `ESPO_SITE_URL=http://localhost:8084`, `ESPO_SECRETS=/tmp/espo/secrets`,
`KOBO_TOKEN_FILE=/tmp/espo/token`, `KOBO_URL=http://host.docker.internal:8099`; then
`./espocrm.sh up --demo-users` and `python3 -I e2e-espo.py --fake-kobo 8099 --secrets
/tmp/espo/secrets --espo-url http://127.0.0.1:8084`.

**The bridge's Kobo account.** On the rig it uses the e2e user's token (`KOBO_TOKEN_FILE`).
On a real box, give it its own Kobo account with only *view submissions* on the form, as
for kobo-dash's `_dash` accounts.

**Another form.** Copy the template, set `BRIDGE_TEMPLATE` in `espocrm.env`, and run
`./espocrm.sh setup`: it adds the new teams and fields and updates changed options. It
doesn't delete fields a template no longer uses.

**Backups.** `./espocrm.sh backup` writes a database dump, EspoCRM's files and the secrets
to `/root/backups/espocrm-<time>/` (owner-only: the cases hold personal data).
`restore <dir>` puts one back on the same box. To restore onto another box, copy the backup's
`secrets` to `$ESPO_SECRETS` first, because the database password inside the backup is the old box's.

## How it works, and why

- **Polling, not KPI's REST Services.** Nothing changes in Kobo's config (REST Services
  to a private address would need KPI's SSRF allow-list), and after either side has been
  down the next pass catches up. The cursor is the last submission `_id` per project. Before
  creating a case, the bridge looks it up by the submission's uuid, so a lost cursor never
  duplicates one. If EspoCRM fails mid-pass, the cursor stays before the failed submission.
  Default: every 30 s.
- **Kobo through the edge.** The bridge resolves `kf.kobo.local` to `host-gateway`, i.e.
  the box's own edge nginx on port 80, so a changed box IP doesn't break it. (The rig's
  `.run.conf` still had a previous droplet's IP; `agents.sh` reads it for kobo-mcp.)
- **Offline.** EspoCRM's daily checks for new versions of itself and its extensions call
  `s.espocrm.com`. Setup turns them off (`adminNotificationsNewVersion`,
  `adminNotificationsNewExtensionVersion`). No SMTP is configured, so EspoCRM sends no email.
  Maps and reCAPTCHA are off by default. The UI bundles its fonts and scripts.
- **Only free EspoCRM features** (as in Ponto): fields, layouts, roles and the API. No BPM
  (that's the paid Advanced Pack).
- **Logs** carry ids and counts, never answers.

## Tested (2026-10-30)

- Unit tests: 9 pass (here and on the rig).
- Laptop (EspoCRM in Docker, fake Kobo): 26/26.
- Rig, real Kobo through the edge: **27/27 online and 27/27 offline**, including a cold
  start of the stack with outbound traffic blocked. All 9 expected cases opened within
  16–32 s, and the later visit on the next pass. No duplicates. Roles behaved as above.
- **Egress:** a packet capture on the stack's Docker network during the offline run and
  two minutes of EspoCRM's scheduler (plus both version-check jobs run by hand) saw no
  outbound packets. A deliberate connection to 1.1.1.1 afterwards showed up, so the capture
  would have seen one.
- **Footprint:** images 1.6 GB (EspoCRM 951 MB, MariaDB 455 MB, Python 178 MB); data
  ~330 MB after setup; ~200 MB of RAM idle (MariaDB ~115 MB).

## Not done yet (phase 2)

- Case status back to Kobo (an EspoCRM webhook → set the submission's validation status).
- Edited Kobo submissions don't update their case (the cursor only moves forward).
- An EspoCRM MCP for the box's agents (search and summarise cases, add notes; writes ask
  first), and W4-style tasks for it.
- EspoCRM's UI in the pilot languages. It ships ar, es, fr, pt, tr and ~30 others (set
  per user), but not Swahili. The template's labels are English.
- Local HTTPS: case logins go over plain HTTP on the box's Wi-Fi (PLAN §7).
