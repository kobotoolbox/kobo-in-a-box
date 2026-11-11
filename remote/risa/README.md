# RISA dashboard on the box (optional, early draft)

[risa-dashboard](https://github.com/joshuaberetta/risa-dash) for RISA (Rapid Infrastructure
and Service Assessment) responses, at `http://risa.kobo.local`. It puts drone and satellite
imagery, the box's Kobo observations and drawn layers on one map, prints **RISA page 1** to
PDF, and exports a GeoPackage for QGIS and ArcGIS. The plan for RISA on the box is
[RISA-PLAN.md](../../RISA-PLAN.md); risa-dashboard covers its R4 (serve imagery) and R5
(a live RISA map) as its own app. Its guide is at `risa.kobo.local/guide/`.

The app itself is an early draft: pages 2 and 3, response bundles, content packs and the
AI features (simulated so far) are on its own list (its `plans/mvp.md`).

```
browser on the Wi-Fi ── edge nginx :80 ── risa.kobo.local ── web (127.0.0.1:8092) ── PostGIS
                                       │   /fonts/  ──────── maps' tile server        │
                                       │   /media/basemaps/OpenStreetMap.pmtiles      │
                                       │        └─ the box's map file (/opt/maps)     │
                                       └─ kf.kobo.local ──── Kobo ◄── worker ─────────┘
                                                                     (COGs, page 1 in Chromium)
```

## Files

| File | What it is |
|---|---|
| `docker-compose.risa.yml` | `db` (PostGIS 16), `web` (migrates, then serves the API, the app and its guide), `worker` (Procrastinate: imagery to COGs, printing, Kobo syncs) |
| `risa.env` | Images, port, data folder, the box's Kobo as the only server, offline basemaps and fonts, process counts |
| `risa.sh` | `build <checkout>` (online), `up`, `key`, `down`/`logs`/`status`, `backup`/`restore` |
| `demo-kobo.py` | A RISA observation form on the box's Kobo with fictional submissions at the sample site, for trying the Kobo layer and for the guide's screenshots |

The edge route is `risa.*` in `../library/nginx/edge.conf`. `risa.sh up` adds a RISA dashboard
link on `kobo.local`.

## How it fits together

- **Offline settings.** `ALLOWED_SERVERS=http://kf.kobo.local` (only the box's Kobo, plain
  http), `ONLINE_BASEMAPS=false` (no OpenFreeMap, Esri or OSM).
- **The box's map as the basemap.** RISA lists `*.pmtiles` files under `media/basemaps/`.
  `risa.sh up` links `OpenStreetMap.pmtiles` there to the box's map (`maps.sh add`), which the
  containers see read-only at `/data/maps`, and the edge serves that file itself with range
  requests rather than through the app. One copy of the map on the box.
- **Label fonts.** `GLYPHS_URL` is `risa.kobo.local/fonts/…`, which the edge proxies to the
  maps' tile server. RISA labels in Noto Sans Bold, which Protomaps' fonts don't have, so the
  edge serves Noto Sans Medium for it. A font setting in RISA would be cleaner.
- **Names, not container addresses.** The containers reach `kf.kobo.local` and
  `risa.kobo.local` through the edge (`host-gateway`), so the worker's Chromium prints page 1
  with the same basemap and font URLs a browser uses.
- **Keys made on the first start** (`$RISA_SECRETS`, owner-only): `SECRET_KEY`, `TOKEN_KEY`
  (encrypts the Kobo tokens responses connect with), the database password and the **create
  key**, which is needed to start a response (`./risa.sh key`). Each response then has its own
  edit key; viewing is open on the Wi-Fi. There are no box accounts in it yet.
- **Load.** Converting an orthomosaic and printing at 300 dpi are the heavy jobs. One worker
  process (`RISA_WORKER_CONCURRENCY=1`) on kits that also run the AI models.
- **Backups.** `risa.sh backup` writes the database (`pg_dump`), the keys and the files
  (imagery, printed pages, exports; not the basemap link). Not yet in `box/backup.sh`, the
  pack or `firstboot.sh` (below).

## Try it on the rig

```sh
# online: the image from a risa-dashboard checkout at RISA_IMAGE's commit
git clone https://github.com/joshuaberetta/risa-dash.git /root/src/risa-dashboard
./risa.sh build /root/src/risa-dashboard
./risa.sh up
./risa.sh key        # the create key, for "New response"
```

Then, from a laptop with `risa.kobo.local` in its hosts file (or the box's DNS), open
`http://risa.kobo.local`, make a response and a site, upload an orthomosaic, connect a Kobo
project on `http://kf.kobo.local` with a Kobo token, and print page 1.

The sample the guide's screenshots use (`../../site/risa-shots.py`), on the rig: risa-dashboard's
`scripts/seed_sample.py --api http://127.0.0.1:8092` with its Haiti orthomosaic (the create key
in `CREATE_KEY`), then `python3 -I box/kobo-account.py risa_demo /root/risa-demo-token` and
`python3 -I risa/demo-kobo.py /root/risa-demo-token`, and connect that project to the site.

Tested 2026-11-11 on the GPU rig (`kobo-box-gpu`) with `offline.sh on`: the 66 MB sample
orthomosaic made into a COG, the box's Kobo project (13 submissions) connected and synced, page 1
printed in about 6 s, the app on the box's map and fonts.

## Not done yet

- **Next time a rig is up:** move `RISA_IMAGE` to risa-dashboard `8fdd30f` or later, which has
  `MAP_FONT`/`MAP_FONT_BOLD`. Set `MAP_FONT_BOLD=Noto Sans Medium` in the compose file, point
  `RISA_GLYPHS_URL` at `maps.kobo.local/fonts/…`, and drop the `/fonts/` rewrite from the
  `risa.*` route in `edge.conf`. Then re-test with `offline.sh on`: labels on the map and on page 1.

- `firstboot.sh`, `pack.sh`, `update.sh`, `box/backup.sh` and the status page don't know about
  it yet: on a box made from a pack, RISA isn't there.
- Kobo tokens are pasted by hand, per response. The dashboards' approach (`dash.sh account`:
  a view-only Kobo account per user) would fit later.
- Not measured on the CPU-only kit or the ARM kit. The image is about 1.8 GB, and PostGIS
  another 0.6 GB.
