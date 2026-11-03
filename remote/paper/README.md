# Paper forms on the box (W13)

[kobo-field-forms](https://github.com/joshuaberetta/kobo-field-forms) (`kff`) at
`http://paper.kobo.local`: print numbered sheets from a deployed Kobo form, fill them in
by hand, scan or photograph them, check what was read, and submit the answers to the
box's Kobo. Nothing leaves the box. PLAN 3l.

| File | What it is |
|---|---|
| `paper.env` | The image (pinned to a kff commit), port (127.0.0.1:8087), where the store lives, the Kobo account's token, the vision model |
| `docker-compose.paper.yml` | `kff`: kff's web app, on Kobo's frontend network so it reaches the batch model as `llm` |
| `paper.sh` | `build <checkout>` (online), `up`, `down`, `logs`, `status`, `e2e`, `backup`, `restore` |

## How it fits the box

- **Kobo:** through the edge as `http://kf.kobo.local` (`host-gateway`, like the case
  bridge), with `KOBO_ALLOW_HTTP=true` because the box's network is plain http.
- **Account:** firstboot.sh's `paper` step makes `paper-forms` (box/kobo-account.py: no
  password, not a superuser, sees only the forms shared with it). Share a form with it in
  Kobo with "Add submissions" to print it. Submissions are made as `paper-forms`.
- **Password:** kff has no sign-in of its own, so the app asks for a password on every
  request (`KFF_WEB_PASSWORD`, any username), generated per box into `/root/paper.secrets`
  and printed on the label card. The Kobo token stays in the app; browsers never see it.
- **Handwriting:** read by the box's batch model (Gemma 4 E4B with its mmproj, `ai.sh`),
  shared with KPI's translation and qual. Without it, choices and numbers still read and
  text is flagged for typing in; the status page says so (amber).
- **Store:** `/var/lib/kobo-box/paper` (forms, printed batches, scans, readings). `backup.sh`
  includes it (the nightly `--no-media` run only the database, like Kobo's media) and puts
  it back on a restore, the account's token too.
- **Kit:** `pack.sh` saves every image a container runs, so a rig with paper forms up
  packs the kff image; `firstboot.sh` starts it when the image is there.

## On the rig

```bash
# Online, once per kff commit: the checkout copied next to kobo-box-ai
./paper.sh build /root/kobo-field-forms
./paper.sh up                     # password in /root/paper.secrets
./paper.sh e2e --sheets 2         # kff's end-to-end test against this box's Kobo
```

`paper.sh e2e` runs kff's own test in a throwaway container with a separate store: it
creates a `kff-e2e-*` project as the token's user, fills in synthetic sheets for each print
profile, scans, reads and submits them, compares what Kobo stored, and deletes the project.
