# Dashboards on the box (W9)

Live dashboards of Kobo data that anyone on the box's Wi-Fi can open, made by the box's
assistant through kobo-mcp's dashboard tools (PLAN.md §3h). Everything runs on the box:
[kobo-dash](https://github.com/kobotoolbox) for the dashboards, its own Postgres, and the
box's one kobo-mcp, which the assistant (OpenCode) uses for all its Kobo tools and which
signs dashboard owners in.

```
browser on the Wi-Fi ── edge nginx :80 ── dash.kobo.local ── kobo-dash (web) ── Postgres
                                       │                     kobo-dash (poller) ─┘
                                       ├─ mcp.kobo.local ─── kobo-mcp ── kf.kobo.local
OpenCode (agents/) ────────────────────┘
```

## Files

| File | What it is |
|---|---|
| `docker-compose.dash.yml` | `db` (Postgres 17), `dash` (kobo-dash's web app, on 127.0.0.1:8086; migrates, then serves), `dash-worker` (the poller), `kobo-mcp` (127.0.0.1:8085) |
| `dash.env` | Images and their source trees, ports, kobo-mcp's tool profiles, the maps folder and basemap |
| `dash.sh` | `build` (online), `up`, `account <user>`, `boundaries`, `tiles`, `down`/`logs`/`status`, `backup`/`restore` |
| `mbtiles.py` | Unpacks a raster MBTiles file into `{z}/{x}/{y}.png` for the edge to serve (stdlib only) |
| `e2e-dash.py` | End to end on the box, through the edge (below) |
| `e2e-dash-espo.py` | The box's case management as a dashboard source: EspoCRM feeds (below) |

The edge routes are in `../library/nginx/edge.conf` (`dash.*`, `mcp.*`, and `/tiles/` on
`kobo.local`). `firstboot.sh` runs `dash.sh up` when the pack has kobo-dash's image; the
status page has a Dashboards row; `backup.sh` includes kobo-dash's database and keys.

## How it fits together

**Names, not container addresses.** kobo-dash, kobo-mcp and OpenCode reach each other and
Kobo as `dash.`, `mcp.` and `kf.kobo.local` through the edge (`host-gateway`), as a browser
does. The sign-in assertions name those URLs, and kobo-mcp only answers to its own host
name (its DNS-rebinding guard), so this is simpler than a second set of internal names.

**Plain http.** The box has no certificates yet (PLAN §7). Both apps accept http for these
names only:
- kobo-dash: `ALLOWED_SERVERS=http://kf.kobo.local`, an http `PUBLIC_URL` (cookies without
  `Secure`), an http tile URL, evidence links to `http://kobo.local` (all 2026-10-29).
- kobo-mcp: `HTTP_KOBO_HOSTS` (W3), and two settings added for this (branch `w9-box`):
  - `MCP_OAUTH=false`. OAuth for MCP clients needs an https issuer, and the MCP SDK
    refuses an http one, so with `OAUTH_KEYS` set kobo-mcp crashed at start. The sign-in
    page doesn't need it: kobo-dash's sign-in uses kobo-mcp's own `/login` and `/sso/*`.
    The agent uses header mode, which it did anyway: on a box, an OAuth sign-in would open
    its browser on the box, not on the user's laptop.
  - `PUBLIC_KOBO_SERVERS=false`. Only the box's Kobo, so the sign-in page doesn't offer
    Global and EU (unreachable offline), and a token with no server goes to the box's Kobo.

  Since 2026-11-11 the box builds kobo-mcp from `w9-box-main`: those three commits rebased
  onto kobo-mcp `main` 3398982 (local worktree `kobo-mcp-w9-main`; not pushed), which needs
  kobo-dash `main` from 2026-11-03 or later (the role check on `/roles`).
- kobo-dash (`main` a2b86cd, 2026-11-10): `LOCAL_ESPO_ORIGINS=http://cases.kobo.local`, so
  the box's own EspoCRM can be a dashboard's source over plain http (EspoCRM feeds, kobo-dash
  `/admin/espo`; kobo-mcp's `list_espo_connections`, `create_espo_feed`, `update_espo_feed`).
  Its containers resolve `cases.kobo.local` to the host's edge. Tested by `e2e-dash-espo.py`
  (below).

**Owners and their dashboard accounts.** kobo-dash never holds an owner's own token. It
reads each owner's projects through a second Kobo account of theirs, which only ever gets
view access to the projects they make dashboards of. `dash.sh account alice` makes
`alice_dash` (no password; it never signs in) and saves its token in kobo-dash as alice's,
so nobody copies a token by hand. When the assistant makes a dashboard, kobo-mcp shares
the project with `alice_dash`, view only.

**Sharing on the Wi-Fi.** A dashboard starts offline (nobody can open it). "Public" means
anyone on the box's Wi-Fi with the link; "password" for anything sensitive. kobo-mcp's
tools say so, and the agent asks before publishing (OpenCode's `ask` rule).

**Maps.** The content pack's `maps/` folder becomes `/opt/maps`:
- `boundaries/`: administrative areas for the deployment countries,
  `dash.sh boundaries KEN UGA --levels ADM0,ADM1,ADM2` (online, at the factory; kobo-dash's
  own fetcher, the same simplified layers as its settings page). With `BOUNDARIES_DIR` set,
  "get administrative areas" reads only these and never calls geoBoundaries.
- `tiles/`: a raster basemap for the region, `dash.sh tiles region.mbtiles`. `up` then sets
  `TILE_URL=http://kobo.local/tiles/{z}/{x}/{y}.png` with the file's attribution and
  deepest zoom. The MBTiles must be rendered from an OpenStreetMap extract (Geofabrik +
  a renderer); OpenStreetMap's tile policy forbids bulk downloads from its servers. With
  no tiles, maps have no basemap; areas, shading and points still draw.

**Keys.** `dash.sh up` makes them on the first start (`/root/dash.secrets`): kobo-mcp's
`OAUTH_KEYS` and Ed25519 `DASH_SIGNING_KEY` (kobo-dash gets the public half), kobo-dash's
`SECRET_KEY` and `CRED_KEYS` (which encrypt the dashboard accounts' tokens), and the
database password. A backup carries them: restoring onto another box takes the backup's
keys (stored tokens can't be read without them) and keeps that box's database password.

## Running it

```bash
./dash.sh build                 # online: kobo-dash and kobo-mcp from KOBO_DASH_SRC / KOBO_MCP_SRC
./dash.sh up
./dash.sh account e2e           # e2e's dashboard account
./dash.sh boundaries LSO --levels ADM0,ADM1,ADM2   # online
./dash.sh tiles region.mbtiles
```

OpenCode (`../agents/agents.sh up`) uses this kobo-mcp at `http://mcp.kobo.local/mcp`; start
it after `dash.sh up`. Its container waits for kobo-mcp's health check before starting
OpenCode, which connects to its MCP servers only once.

## Tests

`e2e-dash.py`, run on the box in the kobo-mcp image (see its docstring), makes a throwaway
project and goes through what an owner and the assistant do:
- An owner signs in through kobo-mcp's page, which offers only the box's Kobo.
- Their dashboard account is in place.
- The assistant's tools (header mode, as OpenCode) add 12 submissions and make a
  dashboard, sharing the project with the dashboard account, view only.
- The dashboard stays closed until it's made public; then the poller fills it, and the
  viewer opens for anyone on the Wi-Fi. Its page and security policy load nothing from
  outside the box.
- An open page's live-update stream hears about a 13th submission.
- With `--maps LSO`: Lesotho's regions come from the maps folder into the dashboard, and
  the viewer gets the box's basemap and a tile.
- Closed again, then deleted, and the project archived.

**2026-11-03, on the rig with real Kobo:** 23/23 online; 28/28 offline with `--maps LSO`.
- A cold start of the stack with outbound traffic blocked worked.
- **Egress:** during the offline run and two minutes of idling, a packet capture on the
  stack's Docker network saw nothing addressed outside the box. A deliberate connection
  to 1.1.1.1 afterwards showed up (3 packets), so the capture would have seen one.
- After a reboot, everything came back by itself, and OpenCode had both MCP servers,
  `kobo` (through `mcp.kobo.local`) and `cases`, connected.
- **Backups:** `dash.sh backup` + `restore` brought back a wiped database. Restoring onto
  "another box" (new keys, same database password) took the backup's keys, and the full
  test then passed with the restored dashboard account. `backup.sh run` includes `dash/`.
- New-submission events reach an open page in about a minute: `refresh_dashboard` runs at
  most once a minute, and the poller's own interval is the dashboard's refresh setting.
- **Footprint:** images 1.3 GB (Postgres 646 MB, kobo-dash 361 MB, kobo-mcp 311 MB); about
  255 MB of RAM idle; the database 50 MB after the tests.

`e2e-dash-espo.py` (same image, plus EspoCRM's admin password: its docstring) does the
EspoCRM feeds: an API user reading one team's cases and five of their fields (as
kobo-espo-bridge's `create_dashboard_feed` makes it); its key saved in kobo-dash's admin page
with `http://cases.kobo.local`; `list_espo_connections` (no key shown); a feed through
`create_espo_feed`; a case edited in EspoCRM read again (`update_espo_feed`); then the
table, connection, user and role removed.

**2026-11-11, on the rig offline** (kobo-dash `main` a2b86cd, kobo-mcp `w9-box-main`):
15/15. The feed had the team's 123 cases of 228, the asked-for columns and no caregiver
details; the edit gave version 2. **Found:** asked for a field the API user's role can't
read (`cCaregiverPhone`), kobo-dash makes the column anyway, since EspoCRM's metadata lists
every field; EspoCRM withholds the values, so it stays empty (checked), but kobo-dash's
"or the API user can't read it" refusal doesn't happen. For kobo-dash: check fields against
a record the key reads, or EspoCRM's `/App/user` ACL (`fieldTable`). Also: the admin page's
"EspoCRM address" input is unstyled (`type=url`, `site/static/dash/espo-card.jpg`). On a box
updated offline from the older pack: PASS (10 cases of the team), and `e2e-dash.py` 23 ok.
`--keep` leaves the connection and feed for `site/dash-espo-shots.py`.

## Not done yet

- A basemap for a real region: render MBTiles from the deployment countries' OpenStreetMap
  extract once they're chosen (the test used made-up grey tiles).
- About 10 dashboard tasks in W4's set, scored on the agent models (needs the GPU rig).
- Offline `desk_review` (the agent's research for narratives) needs the local knowledge
  base (W10).
- Dashboards in a real browser on the box's Wi-Fi, with the hotspot (W12).
- Proposing kobo-mcp's two settings upstream (branch `w9-box`).
