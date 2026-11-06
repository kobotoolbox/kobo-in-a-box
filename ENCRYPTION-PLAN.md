# Encrypted forms on the box: plan

Goal: a box admin turns on encryption for a form at `kobo.local/keys`, phones and web forms
encrypt each submission before it leaves them, the box stores only ciphertext, and the
admin downloads the decrypted data by typing a passphrase. This works the way ODK Central's
*managed encryption* does, on top of KoboToolbox.

Status (2026-11-06): planned, not built. Workstream **W16** in PLAN.md (section 3o); Linear milestone "W16 · Encrypted forms", PRODUCT-343 to PRODUCT-350.

Sources: [Encrypted forms](https://docs.getodk.org/encrypted-forms/),
[Central encryption](https://docs.getodk.org/central-encryption/),
[Central API encryption](https://docs.getodk.org/central-api-encryption/).

## 1. What Kobo already does, and what it doesn't

**Already there** (kpi `main`, checked 2026-11-06):
- KPI marks a form as encrypted when its XLSForm settings have both `public_key` and
  `submission_url` (`logger/models/xform.py`, `_set_encrypted_field`). The asset API
  reports this as `deployment__encrypted`.
- KoboCollect encrypts finalized submissions with ODK's scheme. Enketo encrypts too (to
  check on the box's Enketo version).
- KPI stores the submission manifest and its `submission.xml.enc` and `*.enc` media as
  attachments. It also serves ODK's Briefcase API (`view/submissionList`,
  `view/downloadSubmission`).

**Missing**, and what Central has:

| Central (managed encryption) | Kobo today | On the box |
|---|---|---|
| The server makes the RSA key pair and keeps the private key locked with a passphrase it never stores | You make keys with openssl and paste the public key into the XLSForm | `kobo.local/keys` makes and keeps the key pair, locked with the admin's passphrase |
| Turned on per project; forms get the key automatically | Set by hand in each XLSForm's settings | Turned on per form from the page, which also redeploys the form |
| Decrypted CSV/ZIP export when you type the passphrase | No decryption. Briefcase plus the private key file, on a laptop | Decrypted export from the page; the passphrase and unlocked key are kept only for that request |
| Passphrase hint | — | Hint kept with the key |

## 2. Design

### Keys

- **A named key** has an RSA-2048 pair (ODK's size). The private key is stored as a
  passphrase-encrypted PKCS#8 PEM (Python `cryptography`, `BestAvailableEncryption`). It
  sits next to its public key, hint, fingerprint and form list in
  `/etc/kobo-box/keys/<id>.json` (owner-only). We use a standard locked PEM rather than our
  own format, so `openssl pkey` can unlock it off the box. That also makes Briefcase a
  fallback decryptor.
- **The passphrase is never written anywhere.** It's not on the label card or in the
  journal. The page asks for it twice, enforces a minimum length, and says plainly that a
  lost passphrase means the data can't be decrypted, ever (Central's warning).
- **One key can cover many forms.** That's Central's "per project" in Kobo terms: a team
  usually wants one passphrase for its whole survey.
- **Backups:** `/etc/kobo-box` is already in `KOBOBACKUP` backups, so the locked key travels
  with the data. A restore gives back a key that still needs its passphrase. The page also
  exports the locked key file (for a second stick kept with the passphrase holder) and the
  public key alone.

### Turning it on for a form

- The page sets `public_key` and `submission_url` in the asset's content settings and
  redeploys, as a superuser through KPI. Data collected before that stays readable, as in
  Central. Phones pick up the new version through the box's Collect setting that updates
  forms by themselves (W15).
- **`submission_url` on the box:** `http://kc.kobo.local/submission` resolves to whichever
  box a phone is on. Things to test: the exact path KPI accepts, a phone set up with a
  per-box name (`kc.<name>.local`), and what happens to the setting when someone edits the
  form in the form builder and redeploys.
- **No way to turn it off from the page**, as in Central. Taking encryption off an
  in-progress survey leaves a mix of plaintext and ciphertext that people misread. A form
  that needs it off gets copied to a new form.
- **Forms with someone else's key** (a `public_key` already in the XLSForm) are left alone
  and listed as "encrypted, key not on this box".

### Decrypting

- `kobo.local/keys` → form → *Download decrypted data*. The admin types the passphrase, and
  the box:
  1. fetches each manifest and its `.enc` files through KPI;
  2. unlocks the key in memory;
  3. decrypts each submission;
  4. checks its signature;
  5. sends back a ZIP holding an XLSX/CSV of the data (one column per question, as Kobo's
     own export lays them out), the media files, and a `signature` column (good/bad,
     like Briefcase).

  Nothing decrypted is written to disk on the box, except as a temporary file in `tmpfs`
  if the ZIP is too big to build in memory. A wrong passphrase gets a plain error.
- **The decryptor** follows ODK's published scheme: the AES-256 symmetric key encrypted
  with RSA-OAEP, AES-CFB data, per-file IVs from the MD5 of instanceID plus the key, and an
  MD5 signature over form ID, version, key, instanceID and file hashes. Before writing it,
  read Central's `lib/util/crypto.js` and Briefcase's decryptor for the exact padding and
  OAEP hash. The details above are from memory. The proof is decrypting real KoboCollect
  and Enketo submissions, not our own encryptor.
- **Building the export:** use formpack, Kobo's own export library (already in the KPI
  image), on the decrypted XML, so the columns match a normal Kobo export. The simplest way
  is to run the decrypt-and-export step inside the KPI container (`docker exec`), with the
  passphrase sent on stdin, never as an argument.
- Also a standalone `box/decrypt.py`: the same code for a laptop, with the exported locked
  key and a folder of encrypted submissions.

### Where the page lives

`box/keys.py`, `kobo-box-keys.service`, at `kobo.local/keys`. It works like
`box/users.py`: Kobo superusers sign in with their Kobo password, with the same sessions
and lockout, and logs carry no form data. Move the sign-in, sessions and page helpers out
of `users.py` into a small shared module rather than copying them. Add a nav row across the
admin pages (Accounts · KoboCollect · Encryption).

### Kits and the hub (W14)

**Recommended:** kits encrypt, the hub decrypts. A field kit holds only the public key, in
the form. The locked private key lives on the hub, or wherever the passphrase holder is. A
stolen kit then gives away nothing, even if someone forces the passphrase out of its
operator. The page imports either a public key alone ("this box can collect but not
decrypt") or the locked key file.

**kobo-transfer breaks encrypted submissions as it is.** `transfer/xml.py` replaces the
root element's attributes (which drops `encrypted="yes"`), rewrites `id`/`version`, and
adds `formhub/uuid` and `__version__`. The hub would then store the manifest as a
plaintext submission with nothing in it. The signature covers form ID and version, so it
would check as bad even if decryption worked. It needs an encrypted mode:
- send the manifest unchanged, except for the root `id` the hub's form expects;
- keep `encrypted="yes"`;
- copy every `.enc` attachment byte for byte;
- skip edit handling (encrypted submissions can't be edited).

The decryptor checks the signature against the form ID the phone signed (the kit's), so
this needs either a record of the original ID or a check that accepts the kit's ID. The fix
goes on the kobo-transfer branch next to PR #60.

### What an encrypted form loses on the box

Users choose this knowingly, so the page and the guide list it:

| Feature | With an encrypted form |
|---|---|
| Kobo data table, maps, reports, Kobo's exports | Metadata only (submitter, dates, validation status) |
| KPI AI: transcription, translation, qual (W2) | Nothing to process: the audio and text are ciphertext |
| Agents, kobo-mcp, dashboards (W4, W9) | No data. kobo-mcp should say "this form is encrypted" rather than return empty results |
| Case bridge (W11) | Can't open cases from it |
| Paper forms (W13) | kff sends plaintext XML. Phase 1: kff refuses encrypted forms. Later: kff encrypts before it submits (the encryptor written for the tests could do this) |
| Editing submissions in Enketo | Not possible |
| Sync to a KoboToolbox server (W14) | Works once kobo-transfer has the fix; the server sees only ciphertext, which is the point |

A later option, **not** in this plan, is a "decrypted working copy": decrypted data loaded
into a separate, restricted project so AI and agents can use it. It undoes much of what
encryption is for, so it's a decision for the partner, not a default (section 5).

### What encryption doesn't protect (put in the guide)

From the ODK docs:
- Drafts, and values kept by the last-saved feature, stay in plaintext on the phone.
- Collect can leave plaintext copies behind (camera apps, force-closes). Wipe phones
  between deployments.
- Nothing stops fake or replaced submissions.
- The blank forms, the QR codes and the accounts aren't encrypted.
- Encryption doesn't replace HTTPS on the admin pages: over the box's plain HTTP, the
  passphrase crosses the Wi-Fi when someone types it in. This adds weight to the open HTTP
  vs local HTTPS question (PLAN.md section 7). Until that's settled, decrypt from a device
  plugged into the box, or on the box itself.

## 3. Testing on the rig

The CPU rig is enough; this needs no GPU. All checks run with `offline.sh on`.
`remote/e2e-encryption.sh`, scored like `e2e-users.sh`:

1. **Keys:** make a key on the page; the passphrase is in no file and no journal line; the
   locked PEM opens with `openssl pkey` and the passphrase, and not without it.
2. **Turn on** encryption for a form with a text question, a select, a GPS point, a photo
   and an audio clip; the deployed XForm carries `base64RsaPublicKey` and
   `submission_url`, and KPI reports `deployment__encrypted`.
3. **Submit three ways:**
   - KoboCollect on the stand-in phone (`remote/phone.sh`, redroid), set up from the W15
     QR code;
   - Enketo in a browser (Playwright, as in `e2e-signin`);
   - a Python encryptor that follows ODK's scheme, for many submissions quickly.
4. **Nothing in plaintext:** a unique canary string in a text answer and in the photo's
   bytes. After submitting, search a Postgres dump, a Mongo dump, attachment storage, Redis
   and the logs for the canary. It must be in none of them.
5. **Decrypt:** a wrong passphrase is refused. With the right one, every value and media
   checksum matches what was entered, and every signature is good. A tampered `.enc` file
   shows as bad.
6. **Earlier data:** submissions made before encryption still export through Kobo as
   usual.
7. **Kits:** two rigs. The kit holds only the public key and the hub holds the locked key.
   Sync with the kobo-transfer fix, then decrypt at the hub. The kit's page can't decrypt.
   Sending again sends nothing new.
8. **Backups:** back up, restore onto a fresh box, decrypt with the same passphrase.
9. **Other features fail clearly:** kobo-mcp, kff and the case bridge say the form is
   encrypted instead of failing silently or making something up.

## 4. Work (W16, ~2 weeks for one developer)

- [ ] Read Central's `crypto.js` and Briefcase's decryptor; write `box/odk_crypto.py`
      (decrypt, check signature; encrypt, for tests and later kff) with tests on fixtures
      made by real Collect
- [ ] `box/keys.py` at `kobo.local/keys`: make/import/export keys, turn a form on, decrypted
      export; shared sign-in module with `users.py`; edge route, service, `box.sh install`
- [ ] Find out the `submission_url` path KPI accepts and whether form-builder redeploys keep
      the settings
- [ ] kobo-transfer: an encrypted mode (manifest unchanged, `.enc` attachments as they are,
      no edit handling)
- [ ] kobo-mcp, kff and the case bridge: notice encrypted forms and say so
- [ ] `remote/e2e-encryption.sh` (section 3) on the rig, offline; then on a box from a pack
- [ ] `box/decrypt.py` for laptops
- [ ] User guide: when to use encryption, what it costs (section 2 table), the passphrase
      rules, screenshots (`site/keys-shots.py`)
- [ ] PLAN.md: a 3o section and W16; Linear milestone "W16 · Encrypted forms"

## 5. Decisions needed

Recommended defaults in bold:
1. **Who manages keys:** **Kobo superusers only in phase 1** (like accounts). Later, form
   owners for their own forms.
2. **Do kits ever hold the private key:** **no, by default**. Allowed for single-box
   deployments.
3. **One key per team covering many forms** (Central's per-project model), or one per form.
4. **No decrypted working copy inside Kobo**, so no AI or agents on encrypted forms, unless
   a partner asks for it and accepts the trade-off.
