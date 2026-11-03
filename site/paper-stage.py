"""
Demo data for the paper forms screenshots (site/paper-shots.py). Runs ON THE DROPLET, in
the running paper forms app's container, so it uses the box's own Kobo, model and store:

    docker exec -i kobo-paper-kff-1 python - < site/paper-stage.py

Deploys kobo-field-forms' test form to the box's Kobo as `kff-e2e-paper-demo` (the only
name kff may make and delete), fetches it into the app's store like a user would, then
prints, fills in, scans and reads 3 synthetic sheets with the box's vision model. Writes a
photographed sheet to /data/demo-photo.png for the upload screenshot, and prints the
form's ids as JSON. Delete the project afterwards (paper-shots.py prints how).
"""
import json
import random
from importlib import resources

import cv2
import numpy as np

from kff.bench import run
from kff.config import Settings
from kff.fetch import fetch_form
from kff.form.rules import rules
from kff.kobo.client import KoboClient
from kff.kobo.deploy import TEST_PREFIX, create_and_deploy
from kff.read.vlm import VlmConfig, VlmReader
from kff.render.options import RenderOptions
from kff.render.pdf import render
from kff.store import Store, new_batch_id
from kff.synth.answers import random_answers
from kff.synth.degrade import Degrade, degrade
from kff.synth.fill import filled_pages

settings = Settings.from_env()
client = KoboClient(settings)
content = json.loads(resources.files('kff').joinpath('e2e_form.json').read_text())
uid = create_and_deploy(client, f'{TEST_PREFIX}paper-demo', content)
form = fetch_form(client, settings.server, uid)
config = VlmConfig.from_env()
with Store(settings.home) as store:
    form = store.save_form(form)
    run(store, form, RenderOptions(), sheets=3, seed=5, profile='demo',
        vlm=VlmReader(config) if config else None)
    # A sheet as a phone photographs it, for the upload page
    printed = render(form, RenderOptions())
    store.save_layout(printed.layout)
    store.save_sheets(printed.layout_hash, new_batch_id(), [s.id for s in printed.sheets])
    rng = random.Random(8)
    page = filled_pages(printed, random_answers(printed.model, rules(form.content), rng), rng, ppi=150)[0]
    img = cv2.imdecode(np.frombuffer(page, np.uint8), cv2.IMREAD_GRAYSCALE)
    photo, _ = degrade(img, Degrade(rotate_deg=3, perspective=0.03, blur=0.6, noise=4,
                                    jpeg_quality=85, pad_px=90, seed=4))
    cv2.imwrite(str(settings.home / 'demo-photo.png'), photo)
    sheets = [s['sheet_id'] for s in store.scanned_sheets()]
print(json.dumps({'asset_uid': form.asset_uid, 'version_uid': form.version_uid, 'sheets': sheets}))
