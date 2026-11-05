#!/usr/bin/env python3
"""
Screenshots of the knowledge base (W10) for the homepage. Runs ON THE RIG in the Playwright
image, so OpenCode's password never leaves it:

    docker run --rm --network host --ipc=host -v /root/shots:/shots \
      -v /root/kobo-box-ai/site-knowledge-shots.py:/s.py:ro \
      -e OC_PASSWORD="$(docker exec kobo-agents-opencode-1 printenv OPENCODE_SERVER_PASSWORD)" \
      -e SESSIONS="<session id>[,<session id>...]" \
      mcr.microsoft.com/playwright/python:v1.55.0-noble \
      sh -c "pip install -q --break-system-packages playwright==1.55.0; python3 /s.py"

SESSIONS: OpenCode sessions where the assistant answered from the guides (knowledge/
answers.py makes them; its report has the ids). Writes PNGs to /root/shots: each session
in OpenCode's web interface, a cited guide page opened at its section, and the ODK guide
in the library.
"""
import base64
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path('/shots')
OPENCODE = 'http://127.0.0.1:4096'
RULES = 'MAP kobo.local 127.0.0.1'   # the edge nginx on this host answers for the box
PAGES = {
    'k-guide-section': 'http://kobo.local/docs/kobo/es/question_options.html#respuesta-obligatoria',
    'k-odk-page': 'http://kobo.local/docs/odk/form-regex.html',
}


def shot(pg, name, wait=2, full=False):
    time.sleep(wait)
    pg.screenshot(path=str(OUT / f'{name}.png'), full_page=full)
    print('wrote', name, pg.url)


def main():
    OUT.mkdir(exist_ok=True)
    workspace = base64.urlsafe_b64encode(b'/workspace').decode().rstrip('=')
    with sync_playwright() as p:
        b = p.chromium.launch(args=[f'--host-resolver-rules={RULES}'])
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, device_scale_factor=2,
                            http_credentials={'username': 'opencode', 'password': os.environ['OC_PASSWORD']})
        pg = ctx.new_page()
        for i, sid in enumerate(s for s in os.environ.get('SESSIONS', '').split(',') if s):
            pg.goto(f'{OPENCODE}/{workspace}/session/{sid}')
            shot(pg, f'k-answer-{i + 1}', wait=8)
        lib = b.new_page(viewport={'width': 1440, 'height': 900}, device_scale_factor=2)
        for name, url in PAGES.items():
            lib.goto(url)
            shot(lib, name)


if __name__ == '__main__':
    main()
