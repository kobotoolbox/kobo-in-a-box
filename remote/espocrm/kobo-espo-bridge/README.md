# kobo-espo-bridge

Kobo → EspoCRM, and back. A small service that polls KoboToolbox for new submissions and
turns each one into an EspoCRM record (a case, a contact, a site...), routed to the right
team, with the right people notified. It also keeps lists from EspoCRM (open cases, sites,
standards...) on Kobo forms as CSV media, so forms can offer them as choices. And it applies
follow-up visits and edited submissions to the records they're about. Stdlib Python only;
one process per template.

Extracted from [kobo-in-a-box](../kobo-in-a-box) `remote/espocrm/` (W11, 2026-11-03), where
it runs offline on the box, so that the box, [kobo-espo](../kobo-espo) and later connections
share one tested bridge. Formerly kobo-bridge (renamed 2026-11-05). Not to be confused with
kobo-espo, which is one EspoCRM instance using it (its setup, forms, templates and tests).
The bridge's default EspoCRM API user is still called `kobo-bridge`, so existing setups
keep their user.

| File | What it is |
|---|---|
| `bridge.py` | The bridge: `run` (poll every `BRIDGE_POLL_SECONDS`), `once`, `failed DIR`, and `serve`: every connection in one process |
| `connections.py` | `serve`: Kobo connections made in EspoCRM and template files, each set up and polled with its own users and ledger |
| `propose.py` | A template from a Kobo form (`propose`), and what a submission would become (`preview`); writes nothing |
| `espo_mcp/` | The EspoCRM MCP: connecting forms from a conversation, next to kobo-mcp (the only part that needs a package: the MCP SDK) |
| `setup.py` | Sets EspoCRM up for a template: fields, teams, the bridge's API users with only the rights the template needs |
| `fake_kobo.py` | A fake Kobo (the KPI v2 endpoints the bridge uses), for end-to-end tests without a Kobo server |
| `templates/health-referral.toml` | kobo-in-a-box's scenario (community health referrals) |
| `tests/` | Unit tests, Kobo and EspoCRM faked in memory: `PYTHONPATH=.:tests python3 -m unittest discover -s tests` |

## How it works, and why

- **Polling, not Kobo's REST Services.** Nothing changes in Kobo's config, no webhook proxy,
  and after either side has been down the next pass catches up. The cursor is the last
  submission `_id` per project.
- **Never twice.** Before creating a record the bridge looks it up by the submission's
  uuid; with `[record] match`, also by a field (an email, a site code). A lost cursor or
  ledger means a rescan, never a duplicate.
- **One bad submission never blocks the rest.** A submission EspoCRM refuses (a 4xx naming
  the field), or one missing a required answer, is recorded in the ledger
  (`bridge.sqlite`) and retried after 1 min, 10 min, 1 h, then every 6 h, and at once when
  the template or the form changes. "Unreachable" (no connection, 5xx, a refused key) ends
  the pass with the cursor kept. `bridge.py failed DIR` lists what's waiting and why;
  `status.json` has counts and errors, never answers.
- **Least privilege.** Each template's API user can do only what that template needs
  (`setup.py` builds its role): create records of its entity; with `match`, update them;
  with `[requester]`, Contacts and Accounts. It can't read users or delete anything.
- **Only free EspoCRM features**: fields, layouts, roles, the API, and formula. No BPM or
  workflows (the paid Advanced Pack): notifications are @mentions in a note, which core
  EspoCRM turns into notifications (in the app; by email when SMTP is set up).

## Templates

A template (TOML) says which Kobo form becomes which records, and how. All sections but
`[record]` are optional.

```toml
[bridge]                      # the API user setup.py makes for this template
user = "kobo-intake"          # default kobo-bridge
role = "Kobo intake"          # default "Kobo bridge"
secret = "ESPO_INTAKE_API_KEY"  # its key's name in the secrets file

[form]
name = "Kobo support request" # every deployed project with this name the token can see
when = { needs_followup = "yes" }  # only these submissions become records

[record]                      # ([case] is its older name)
entity = "Case"               # any entity: Contact, CSite...
name = "{category}: {summary}"  # {question}: the answer's label
details = [["Notes", "notes"], ["", "description"]]  # lines of the description
required = ["email", "summary"]  # checked before anything is written
match = { emailAddress = "email" }  # update the record that has this answer, don't add one
single_team = true            # one team: the highest-priority matching route's
set = { cSource = "Kobo form" }  # constants
media = "attachments"         # copy the submission's files into this attachment field
media_max_mb = 10             # bigger files are named in the description instead
attachments = true            # (or) links to the files in Kobo; they need a Kobo login
panel = "Request"             # the record page's panel with the template's fields
notify_message = "New request from Kobo:"

[requester]                   # link the record to who sent it
email = "requester_email"     # Contact by email, made if missing
name = "requester_name"
organisation = "organisation" # Account by the answer's label, made if missing
create_account = true

[escalation]                  # unassigned this long after it came in: mention the route's `escalate` users
after_hours = 4

[[route]]                     # every matching route adds its team (or, single_team, the top one)
match = { project = "consortium_a" }  # question = answer; for select_multiple, "includes"
team = "Project: Consortium A"
priority = "High"             # cases
follow_up_hours = 48          # cases: the "Follow up by" date
notify = ["triager"]          # mentioned on each new record
escalate = ["lead-a"]

[[field]]                     # Kobo question -> EspoCRM field
kobo = "category"
espo = "cCategory"            # custom fields of EspoCRM's own entities start with "c"
type = "enum"                 # varchar | text | int | float | date | datetime | enum | multiEnum | personName | link;
                              # left out for select questions (the form says) or existing fields
label = "Category"
options = { forms = "Forms and XLSForm" }  # left out: from the deployed form

[[field]]                     # a link: the record whose `lookup` field has the answer
kobo = "standard"
espo = "standard"             # the link (made in EspoCRM, not by setup.py)
type = "link"
entity = "CStandard"          # setup.py lets the bridge's user read it
lookup = "code"               # left out: the answer is the record's id (from a [[list]] of ids)

[[field]]
kobo = "end"                  # start, end, datetime questions
espo = "registeredAt"
type = "datetime"             # stored in UTC, from Kobo's local time and offset

[[list]]                      # EspoCRM records as a CSV on Kobo forms (select_one_from_file, pulldata)
file = "sites.csv"
entity = "CSite"
team = "Response: Test EQ 1"  # only this team's records
where = { status = ["operational", "needs_repair"] }
columns = { name = "siteCode", label = "{siteCode} · {name}", status = "status" }
forms = ["Site visit"]

[[repeat]]                    # each row of a repeat group: a record of its own
group = "FIGURES_COMMUNITY"   # the repeat group's name
entity = "CActivityLocation"
link = "activity"             # its link to the submission's record
name = "{community}"

[[repeat.field]]              # as [[field]], the row's questions (lookups too)
kobo = "community"
espo = "community"
type = "link"
entity = "CAdminArea"
lookup = "pcode"

[followup]                    # a second form that updates existing records
form = "Site visit"
key = "site"                  # the question that picks the record
match = "siteCode"            # ...by this field (left out: cases by number, cs_<n>)
fields = { condition = "status", visit_date = "lastVisit" }  # only these are written
note = [["By", "visitor"], ["Notes", "visit_notes"]]
user = "kobo-site-visits"     # its own API user: may edit only those fields
media = true                  # the visit's photos, on its note
```

**Media.** With `media`, the files a submission's answers refer to (in repeat groups too;
not deleted ones) are downloaded with the bridge's token, from its own Kobo only (the
URL's host is checked, so a submission can't make it fetch elsewhere), and attached to the
record before it's created. Staff then see them without a Kobo account, with the record's
access rules. As in kobo2logie (`src/lib/kobo.ts`, `attachmentsToForward`). Kobo stores a
file under a cleaned-up name (`site photo (1).jpg` as `site_photo_1.jpg`) and current
servers also give the answer's (`media_file_basename`); for older ones that don't, the
answer is matched by the cleaned-up name. The copy keeps the answer's name.

**Links by lookup.** A `link` field with `lookup` links the one record of `entity` whose
`lookup` field equals the answer: a standard by its code, a district by its pcode. If
there's none, or more than one, the submission is recorded with the count (never a guess)
and tried again on the usual backoff, so a record made later in EspoCRM still gets it.
Looked up before anything is written. (As kobo-connect's `Entity.link.field` headers do,
rodekruis/kobo-connect; its other EspoCRM features the bridge had already.)

**Repeat groups.** With `[[repeat]]`, each row of the repeat group becomes a record of
`entity`, linked to the submission's record by `link` (an activity's communities, its focal
points). Rows are matched again by the submission and their position (`cKoboRow`), so a
retry updates them instead of adding more, and rows a shorter version no longer has are
removed. A row that can't be made (a lookup that finds nothing) is recorded with its row
number; the submission's record and its good rows stay, and the rest come on the retry.
The bridge's role may create, edit and delete that entity's records. `propose` doesn't
write `[[repeat]]` yet: it still leaves repeat groups out, with a warning.

**Datetimes.** Kobo sends `2026-04-23T20:21:06.502+05:30` (the phone's local time and
offset); `datetime` fields store it as EspoCRM's UTC `2026-04-23 14:51:06`. Without an
offset it's taken as UTC. Something else is recorded as `not a date and time`.

kobo-in-a-box's template also has `[espo]` (offline, application name), `[[role]]`,
`[[api_user]]` and `[demo]`, for its staff roles, its assistant and demo users.

**Lists reach every phone with the form.** Only the listed columns go into the CSV; keep
names, phone numbers and other personal data out of them.

## Running it

```bash
# Set EspoCRM up for a template (admin password in the secrets file; API keys are written there)
python3 -I setup.py --template my.toml --url https://espo.example.org --secrets /root/espo.secrets \
    --kobo-url https://kf.example.org --token-file /root/kobo.token

# The bridge (in Docker: python:3.13-slim, this directory mounted read-only)
ESPO_URL=https://espo.example.org ESPO_API_KEY=... KOBO_URL=https://kf.example.org \
KOBO_TOKEN_FILE=/root/kobo.token BRIDGE_TEMPLATE=my.toml BRIDGE_STATE_DIR=/var/lib/bridge \
    python3 -I -u bridge.py run    # -u: logs as they happen (-I ignores PYTHONUNBUFFERED)
```

Optional: `ESPO_FOLLOWUP_API_KEY` (follow-ups), `ESPO_EDITS_API_KEY` (edited submissions,
cases only), `BRIDGE_POLL_SECONDS` (30), `BRIDGE_LIST_MIN_SECONDS` (900: each list upload
is a redeploy of the form), `ESPO_LANGUAGE`.

### Every connection in one service: `bridge.py serve`

Instead of a setup and a bridge per template, one process runs them all:

```bash
ESPO_URL=https://espo.example.org ESPO_ADMIN_PASSWORD=... BRIDGE_SECRETS=/root/bridge.secrets \
KOBO_URL=https://kf.example.org KOBO_TOKEN_FILE=/root/kobo.token \
BRIDGE_TEMPLATES=/etc/bridge/templates BRIDGE_STATE_DIR=/var/lib/bridge \
    python3 -I -u bridge.py serve        # or: serve once
```

- **Connections in EspoCRM.** The first `serve` makes the entity **Kobo connection**
  (`CKoboConnection`). Admins make one with a name and the template pasted in (this
  README's format), and it starts within one pass. No role is given the entity: only
  admins see it. A connection without its own `[bridge]` user gets one,
  `kobo-conn-<its name>`, so two connections never share a user or a role.
- **Template files** (`BRIDGE_TEMPLATES`, `*.toml`) are shown there too, as connections
  whose template is a copy of the file: edit the file. Unticking **Active** pauses one.
- **`serve adopt FILE...`** (with the service stopped) makes template files connection
  records, edited in EspoCRM from then on. A file already shown as a connection keeps its
  record, and its state moves to the record's, so nothing is scanned again; take it out
  of `BRIDGE_TEMPLATES` first (adopt refuses until then). A file with no connection gets
  a new record. Adopting again does nothing, so a deploy can run it every time: kobo-espo
  makes its four connections this way.
- **Setup** (`setup.py`'s `setup()`) runs when a template is new or changed, and every
  `BRIDGE_SETUP_SECONDS` (600) in case its form has a new version. It needs the admin
  password (EspoCRM's API users can't change fields, layouts or roles). The keys it makes
  go to `BRIDGE_SECRETS`.
- **Each connection** has its own state directory (`BRIDGE_STATE_DIR/<file name>` or
  `/<record id>`), ledger and API users, and its status is written to its record (Status,
  Last pass, Waiting, Waiting since, Last error) as well as to `status.json`. One that fails
  doesn't stop the others.
- **`BRIDGE_NAME`** (default `main`): a record is run only by the service named in its
  **Run by**, so a test service doesn't touch the real connections.
- Still **one service per instance**: two would both poll the same forms.

### Connecting a form from a conversation: the EspoCRM MCP (`espo_mcp/`)

An MCP server for an agent (Claude Code, ...) used together with
[kobo-mcp](https://github.com/kobotoolbox/kobo-mcp): kobo-mcp builds, deploys and shares
the form, and this one connects it. Its tools are task-shaped: `bridge_info` (the Kobo
account to share forms with, and the connections), `list_teams`, `list_users`,
`list_entities`, `propose_connection` (a template from the form, what was left out, and a
preview of its latest submission), `preview_template`, `create_connection`,
`update_connection`, `pause_connection`, `resume_connection`, `create_entity`,
`grant_access` (team level only), `test_connection` (waits for the service's next pass,
then shows the record) and `connection_status`. A prompt, **Connect a Kobo form to
EspoCRM**, has the steps.

It also sets up a response and its people, where the instance has responses and cluster
projects (kobo-espo's `CResponse`, `CProject`): `list_projects`, `create_response`,
`create_project` (each with a team of its own), `list_roles`, `invite_user` (a regular
user with a role and teams; EspoCRM emails them a link to set their password when its
outgoing email is set up, and no password passes through the MCP), `add_to_team` and
`remove_from_team`. They never touch admins or API users, or the bridge's and agents'
roles. A prompt, **Set up a response**, has the steps.

- **Only EspoCRM admins.** They connect in one of two ways, and every call checks the user
  is still an active admin, so taking away someone's admin rights ends their access within
  a minute:
  - **signing in** (OAuth; claude.ai, Claude Desktop, or any client that does it): the
    client finds the sign-in itself from the MCP's URL, and the admin types their
    EspoCRM username and password, and their two-factor code if they use one, on the
    MCP's page. EspoCRM checks them (and the session that makes is ended at once); they
    aren't kept. Nothing is stored: client registrations and tokens are sealed with a key
    the MCP makes on its first start (`MCP_OAUTH_KEY_FILE`, next to the keys file);
    deleting it ends everyone's sessions. Tokens last an hour, refreshed for up to 30
    days. `MCP_OAUTH=off` leaves only keys.
  - **a key** each (`espo_mcp/keys.py add <user>`; Claude Code). The keys file keeps
    hashes only.
- **Behind a proxy at a path** (`MCP_PUBLIC_URL=https://espo.example.org/bridge`), clients
  look for two documents at the site's root: route
  `/.well-known/oauth-protected-resource/bridge/*` to the MCP as it is, and
  `/.well-known/oauth-authorization-server/bridge` to its
  `/.well-known/oauth-authorization-server` (kobo-espo's `deploy/Caddyfile` does both).
  Set `MCP_CLIENT_IP_HEADER` to the proxy's `X-Forwarded-For`: the sign-in page allows 10
  attempts per address, and per username, in 10 minutes.
- **Every change takes two calls**: the first shows what would happen and returns a
  `confirm` token for exactly that change (signed, 10 minutes). No tool deletes anything,
  and none reads or writes records in general.
- It runs beside `serve` (`python3 -I espo_mcp/server.py`, Streamable HTTP at `/mcp`, the
  SDK from `espo_mcp/requirements.txt`, or `espo_mcp/Dockerfile`), with the admin password
  and the bridge's Kobo token. It never polls: the service does.

In claude.ai: Settings → Connectors → Add custom connector, the URL
`https://espo.example.org/bridge/mcp`, then sign in. In Claude Code, with a key:

```bash
claude mcp add --transport http espocrm https://espo.example.org/bridge/mcp \
    --header "Authorization: Bearer <the key keys.py printed>"
```

### A template from the form: `propose.py`

```python
import propose
p = propose.propose(form_content, 'Contact', team='Roster', notify=['amina'],
                    existing=fields_espocrm_has)    # {field: type}, optional
p['template']   # TOML, ready to save as a connection (or a file); check it first
p['fields']     # per question: its label, Kobo type, the EspoCRM field and type, a note
p['left_out']   # [(question, why)]: notes, calculations, hidden fields, repeats, metadata
propose.preview(parse_template(p['template']), submission, form_content)
                # the record it would make, its teams, who's told, its files; or why not
```

Each question becomes a field of the matching type (text → varchar, or text if multiline;
integer → int; decimal → float; select_one → enum, its options from the deployed form;
files → the record's attachments; geopoint → varchar). A question named like `summary`
or `site_name` names the record; on Contact, `full_name`, `email` and `phone` are its own
fields and the email is `match`; on Case, the requester's name, email and organisation
are `[requester]`; on a custom entity, a `..._code` question is `match`. On kobo-espo's
forms the proposal matches the hand-written templates but for three naming choices
(kobo-espo `tests/test_propose.py`). Follow-ups and lists have no defaults.

## Tested

- **Unit tests:** 66 (the box's 35; 18 for records other than cases, requesters,
  matching, one team, mentions, escalation, lists, media and its file names, links by
  lookup and datetimes; 13 for `propose` and `preview`).
- **End to end** against EspoCRM 10.0.11: kobo-espo's `tests/cases/connection.py`, 73
  checks with the fake Kobo, 72 on kf.kobotoolbox.org (see its REPORT.md), through
  `serve` since 2026-11-06.
- **kobo-in-a-box**'s own e2e (60 checks on the rig) ran against the version imported here,
  not yet against this one: run it before the box switches.

## For kobo-in-a-box, when it switches

- Point `espocrm.sh` at this repo's `bridge.py` and `setup.py`. `setup.py` now needs
  `--template` (no default), and reads Kobo from `--kobo-url`/`KOBO_SETUP_URL` and
  `--kobo-host`/`KOBO_SETUP_HOST` (no box defaults).
- Its roles, its assistant and its demo users are now in `templates/health-referral.toml`
  (`[[role]]`, `[[api_user]]`, `[demo]`, `[espo]`), not in the code.
- EspoCRM 10 no longer installs with all of `/var/www/html` on one volume (the box uses
  9.3.11): mount `data`, `custom` and `client/custom` separately
  ([docs](https://docs.espocrm.com/administration/docker/installation/#migration-to-espocrm-10)).
