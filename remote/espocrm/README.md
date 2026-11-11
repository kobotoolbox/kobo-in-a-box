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
| `kobo-espo-bridge/` | The bridge, shared with kobo-espo: a copy of [kobo-espo-bridge](https://github.com/joshuaberetta/kobo-espo-bridge) at the commit in its `VERSION`, refreshed with `update-bridge.sh`. The box runs its `bridge.py run` (Kobo → EspoCRM: one case per submission that needs it; stdlib only), its `setup.py` (teams, roles, fields, layouts, the API users and demo users, all from the template; version checks off) and its `templates/health-referral.toml` (the test scenario, with its roles and demo users). Its `tests/` has the scenario's form and visits (`health_fixture.py`) and the unit tests. Not used on the box yet: `serve` (every connection in one process) and the EspoCRM MCP (`espo_mcp/`, which needs the MCP SDK) |
| `e2e-espo.py` | End to end through the running bridge: visits in Kobo → cases, routing, permissions, no external assets; `--ledger`, `--edits`, `--followup` |
| `cases_mcp.py` | The assistant's case tools (MCP server); `test_cases_mcp.py`, `cases-mcp-check.py` |

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

**Roles** (the template's `[[role]]`s, made by the bridge's `setup.py`): *Case worker*: their teams' cases only, can't delete or
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
A box set up by `firstboot.sh` gives it its own: `cases-bridge`, not a superuser and with no
password, which sees only the forms shared with it (*View submissions*). Its token is in
`/etc/kobo-box/cases-bridge.token`, set by `/etc/kobo-box/espocrm.env`, which `espocrm.sh`
reads after `espocrm.env`. The label card tells staff to share the form with it. Test that
path with `e2e-espo.py --edge --share-with cases-bridge`.

**Choices come from the Kobo form.** The template says which questions become which case
fields and how cases are routed; it doesn't copy the form's choices. Setup and the bridge
read them from each project's deployed version (select_one → enum, select_multiple →
multiEnum, the first label). Add a zone in Kobo and redeploy: within 10 minutes
(`kobo-box-cases-setup.timer`, `espocrm.sh setup --if-form-changed`) the field has the
option, and any visit refused for it in the meantime becomes a case by itself. Options are
only ever added, so older cases keep their values. Options written in the template win:
for calculated questions (`referral_reasons` has no choices in the form) or to relabel.
Until a form is shared with the bridge (a new box), select fields wait, and the bridge opens
no case while a mapped field is missing in EspoCRM (it would drop the value silently): the
submissions wait in the ledger until setup has made the field.

**Follow-up visits** (`[followup]` in the template). A second Kobo form records what
happened: the CHW picks the case (`select_one_from_file open_cases.csv`, filtered by their
zone; `pulldata()` shows its reason and due date), says whether the person reached care and
the outcome, and whether to close the case. The bridge keeps `open_cases.csv` on that form:
open cases only, the columns `name` (`cs_<number>`), `label` (`CS-12 · Z2-0147 · Child
danger signs · due 28 Oct`), `zone`, `team`, `reason`, `due` and nothing else, since the
whole file goes to every phone with the form. It's uploaded when it changed, at most every
`BRIDGE_LIST_MIN_SECONDS` (15 min: each upload is a redeploy). Each follow-up then:
- updates **exactly one case**, found by its number, or is recorded in the ledger (0 or
  several matches, no case chosen), never a guess;
- writes **only the listed fields** (`outcome → cReferralOutcome`) and the status
  (`close_case`), as the API user `kobo-followup`, whose role can edit nothing else and
  create nothing (`kobo-bridge`, which opens cases, can't edit any);
- is a **note on the case's stream** with what was recorded, so staff see it even if they
  changed the field since; a **closed case** gets the note only and isn't reopened;
- carries its submission's uuid in the note, so it's never applied twice.
On a box, share the follow-up form with `cases-bridge` with "Edit form" as well as "View
submissions", so it can update the list (the label card says so).

**Edited submissions.** Kobo keeps an edited submission's `_id`, gives it a new `_uuid`
and adds `meta/deprecatedID`. Each pass the bridge asks for those (ids and uuids only) and,
for one whose uuid it hasn't applied, updates its case as `kobo-edits`: the fields that come
from Kobo answers, the name, the description and the uuid, plus a note naming what changed.
Priority, teams, status and staff's fields stay; if the routing rules would now give
something else, the note says so. An edit that means a case is no longer needed adds that
note only; one that means it now is opens the case. (Field-level "no edit" in EspoCRM also
applies when creating, so `kobo-bridge`, which creates cases, can't be the one limited to
these fields: hence the separate user.)

**Case status back to Kobo** (`[kobo_status]`, optional). Cases changed since the last pass
(`modifiedAt`) have their status written onto the submission's validation status, e.g.
Closed → Approved, Pending → On hold. Kobo's data table and exports then show which
referrals were followed up. Leave it out where validation statuses are for data quality.
The bridge's Kobo account needs "Validate submissions" on the form.

**The assistant's case tools** (`cases_mcp.py`, the `cases-mcp` service). An MCP server
(streamable HTTP, JSON responses, stdlib) for OpenCode: `cases_find`, `cases_get`,
`cases_summary`, `cases_add_note`. It acts as `kobo-assistant` (role "Assistant": read cases,
post notes, nothing else), and EspoCRM itself withholds the caregiver's name and phone from
that user (field level), besides the server dropping them. It's on the `kobo-assistant`
Docker network, which only OpenCode joins, not published, and needs the per-box
`CASES_MCP_TOKEN` (`espocrm.sh` makes it; `agents.sh` puts it in OpenCode's config, where
the reads are allowed and `cases_add_note` asks). `cases-mcp-check.py` checks it with the
official MCP client from the kobo-mcp image.

**Languages.** `ESPO_LANGUAGE` (espocrm.env) is EspoCRM's default language; choice labels
come from the Kobo form's translation in that language when it has one ("Français (fr)"
for fr_FR), and a `[[field]]` can carry `labels = { fr_FR = "..." }`.

**API users**, each with only its job: `kobo-bridge` (create and read cases), `kobo-followup`
(the follow-up fields and status), `kobo-edits` (the Kobo-derived fields), `kobo-assistant`
(read, notes; no contact details). Their keys are in the secrets file.

**Another form.** Copy the template, set `BRIDGE_TEMPLATE` in `espocrm.env`, and run
`./espocrm.sh setup`: it adds the new teams and fields and their options. It doesn't
delete fields a template no longer uses.

**Backups.** `./espocrm.sh backup` writes a database dump, EspoCRM's files and the secrets
to `/root/backups/espocrm-<time>/` (owner-only: the cases hold personal data).
`restore <dir>` puts one back, on the same box or another one. From another box (a
replacement), its passwords replace this box's: the MariaDB users get the backup's
passwords, the backup's `secrets` becomes `$ESPO_SECRETS` (the old one is kept as
`.before-restore-<time>`), and the containers are recreated with them. Backups include
the bridge's ledger, so submissions still waiting to become cases are still waiting after
a restore. `box/backup.sh
restore` does this as part of a whole-box restore.

## How it works, and why

- **Polling, not KPI's REST Services.** Nothing changes in Kobo's config (REST Services
  to a private address would need KPI's SSRF allow-list), and after either side has been
  down the next pass catches up. The cursor is the last submission `_id` per project. Before
  creating a case, the bridge looks it up by the submission's uuid, so a lost cursor never
  duplicates one. If EspoCRM fails mid-pass, the cursor stays before the failed submission.
- **One bad submission never blocks the rest** (the ledger, from 510's kobo-connect). When
  EspoCRM refuses a case (a 4xx: e.g. a zone or reason the template doesn't have, which it
  answers with a 400 naming the field) or the template can't map a submission, the bridge
  records it in `bridge.sqlite` and moves on. It's retried after 1 min, 10 min, 1 h, then
  every 6 h, and at once when the template or the form's deployed version changes. A
  submission deleted in Kobo leaves the ledger; nothing else is dropped. Only "unreachable"
  (no connection, 5xx, a refused key) ends the pass with the cursor kept. The ledger and
  `status.json` are in `BRIDGE_STATE_DIR` (`/var/lib/kobo-box/bridge`, owner-only) on the
  host, so the status page and backups see them; `./espocrm.sh failed` lists what's waiting
  and why. A lost ledger means a rescan, which the uuid lookup makes harmless.
- **Status page:** "N Kobo submissions couldn't become cases. They are kept and tried again"
  (amber, call support), and "no cases have come from Kobo for N minutes: the link to
  KoboToolbox is not working" when the bridge hasn't had a good pass for 10 minutes. Only
  failures of projects the bridge can still see count; a deleted or unshared project's stay
  in the ledger in case it comes back.
- **A field EspoCRM doesn't have is silently dropped** (it answers 200). Setup creates
  every template field, so that only happens if one is removed by hand.
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

## Tested

**The ledger (2026-11-03):** 16 unit tests (a refused visit between good ones, backoff,
retry on a template or form change, deleted in Kobo, template errors quoting no answer,
missing team, a project no longer visible, status.json without answers). `e2e-espo.py
--ledger`: a visit in a zone EspoCRM doesn't have is recorded with the reason and the next
visit still becomes a case; with the zone added in EspoCRM, the refused visit became a case
by itself 59 s later, no duplicates: 34/34 on the laptop (fake Kobo), 35/35 on the rig
(real Kobo), where the status page warned meanwhile and went back to green. A bridge whose
token Kobo refuses: the page warns "the link to KoboToolbox is not working". The rig's
switch from the old cursor volume rescanned 13 submissions: 10 existing, no duplicates. The
backup has the ledger.

**Edits, status back, the assistant's tools, languages (2026-11-03):** 35 bridge unit tests
and 7 for the cases tools. `e2e-espo.py --edge --ledger --edits --followup` on the rig, real
Kobo: 60/60, including a visit edited through KoboCAT (deprecatedID) updating its case's
zone and household with a note and nothing else, `kobo-edits` unable to change status or
priority, and a closed case approving its submission in Kobo. `cases-mcp-check.py` with the
official client: 8/8 (a wrong token refused, no contact details). With the assistant's own
key EspoCRM returned neither the phone nor the name. OpenCode showed both `kobo` and
`cases` MCP servers connected after a cold start, once it waited for kobo-mcp to be healthy
(before, it gave up on kobo-mcp for good). In Enketo (`site/cases-shots.py`): the follow-up
form listed the 45 open cases of zone 1 exactly (choice_filter on `open_cases.csv`) and
picking one showed "Referred for: Severe acute malnutrition. Follow up by 1 Nov."
(pulldata).

**Follow-ups (2026-11-03):** 28 unit tests. `e2e-espo.py --edge --ledger --followup` on
the rig, real Kobo: 53/53. The follow-up form gets `open_cases.csv` (header and no names or
phones checked) and it's in the form's OpenRosa manifest for KoboCollect; a follow-up
closes its case with the outcome, nothing else changed, and a note; a second one on the
closed case adds a note only; `kobo-followup` can't change other fields or create cases;
an unknown case number is in the ledger; the closed case leaves the list. Not tested:
`pulldata()` and the `choice_filter` on a real phone and in Enketo.

**Choices from the form (2026-11-03):** 22 unit tests (KPI's stored form and XLSForm style
read alike, a choice added in Kobo reaches the case, template options win, setup only adds
options and keeps labels, the union over several projects, no case before the fields
exist). `e2e-espo.py --ledger` now fixes the refused visit the real way: the zone added
to the Kobo form and redeployed through KPI's API, then `espocrm.sh setup
--if-form-changed`: the visit became a case 22 s later with `cZone = zone_9` and the
form's label in its name, and a second setup did nothing: 37/37 on the laptop, 38/38 on
the rig.

**First version (2026-10-30):**

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

## Not done yet

- Follow-ups on a phone: KoboCollect with `open_cases.csv` (`pulldata`, the zone filter),
  with the hotspot (W12). Enketo is done (`site/cases-shots.py`).
- Follow-ups, edits and status back haven't been run offline yet (they only use the box's
  own Kobo and EspoCRM).
- Photos and repeat groups on the case; locations as linked records (PLAN 3j "Later").
- W4-style agent tasks for the cases tools (needs the GPU rig).
- EspoCRM's UI in Swahili, Hausa or Amharic (EspoCRM doesn't ship them).
- Local HTTPS: case logins go over plain HTTP on the box's Wi-Fi (PLAN §7).
