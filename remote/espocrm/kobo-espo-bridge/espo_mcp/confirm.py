"""The two-call gate in front of every change (as kobo-mcp's tools/confirm.py).

The first call changes nothing: it returns what would change and a `confirm` token. Only
a second call carrying that token acts. The token is signed (HMAC-SHA256), expires after
TTL seconds, and carries the facts it was issued for (the action, its target, a digest of
the template...): `check` compares them with the facts now, so approving one template
can't save another, and a connection changed in between needs a new approval.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

TTL = 600
_KEY = (os.environ.get('MCP_CONFIRM_KEY') or '').encode() or secrets.token_bytes(32)  # one process: enough

AGAIN = ('Call this tool again without `confirm` to get a new one, show the user exactly what it '
         'would do, and pass the token only once they have agreed.')


class Refused(Exception):
    """A change not made, and why: shown to the agent as the tool's error."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def mint(facts, now=None):
    body = _b64(json.dumps({'f': facts, 'exp': int((now or time.time()) + TTL)}, sort_keys=True).encode())
    return body + '.' + _b64(hmac.new(_KEY, body.encode(), hashlib.sha256).digest())


def check(token, facts, now=None):
    """Accept the token only if it was issued here, hasn't expired, and is for these facts."""
    body, _, sig = (token or '').strip().partition('.')
    good = _b64(hmac.new(_KEY, body.encode(), hashlib.sha256).digest())
    try:
        sealed = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4))) \
            if hmac.compare_digest(sig, good) else None
    except ValueError:
        sealed = None
    if not sealed or sealed.get('exp', 0) < (now or time.time()):
        raise Refused(f"`confirm` isn't a valid token, or it has expired (they last {TTL // 60} minutes). "
                      f'Nothing was changed. {AGAIN}')
    if sealed['f'] != facts:
        changed = [k for k in facts if sealed['f'].get(k) != facts[k]]
        raise Refused(f'That token was issued for something else ({", ".join(changed) or "another action"} '
                      f'differs), so nothing was changed. {AGAIN}')
