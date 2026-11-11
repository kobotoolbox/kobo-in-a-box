"""
OAuth sign-in, for claude.ai and Claude Desktop (Claude Code can keep using a key, keys.py).

The SDK serves the authorization server (/authorize, /token, /register and their
metadata); this is its provider, and the sign-in page it sends people to. An EspoCRM admin
signs in with their EspoCRM username and password, and their two-factor code if they use
one. EspoCRM itself checks them, once (/App/user; the session that makes is ended at once),
and they're kept nowhere. Only admins are let in.

Nothing is stored. Client ids, the pending sign-in, codes and tokens are sealed blobs
(AES-GCM, with the key in MCP_OAUTH_KEY_FILE, made on the first start); only the codes and
refresh tokens already used are remembered, in memory, until they expire. A token names
its EspoCRM user, and every call and every refresh checks that user is still an active
admin (as for keys), so taking away someone's admin rights in EspoCRM ends their sessions
within a minute. Deleting the key file and restarting ends everyone's.

Settings (env): MCP_OAUTH (on, or off: keys only), MCP_OAUTH_KEY_FILE (default: next to
MCP_KEYS_FILE), MCP_CLIENT_IP_HEADER (X-Forwarded-For behind Caddy, for the sign-in
page's limit on attempts per address).
"""
import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

import anyio
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from mcp.server.auth.provider import (AccessToken, AuthorizationCode, AuthorizeError, RefreshToken,
                                      RegistrationError, TokenError, construct_redirect_uri)
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from starlette.responses import HTMLResponse, RedirectResponse

from espo_mcp import keys

CLIENT, PENDING, CODE, ACCESS, REFRESH = 'client', 'pending', 'code', 'access', 'refresh'
PENDING_TTL, CODE_TTL, ACCESS_TTL, REFRESH_TTL = 600, 300, 3600, 30 * 86400
ATTEMPTS, ATTEMPTS_WINDOW = 10, 600  # sign-in attempts per address, and per username
COOKIE = 'espo_mcp_signin'
ADMIN_TYPES = ('admin', 'super-admin')


def enabled(env=os.environ):
    return env.get('MCP_OAUTH', 'on').lower() not in ('off', '0', 'no', 'false')


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def unb64(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def key_file(env=os.environ):
    return Path(env.get('MCP_OAUTH_KEY_FILE') or keys.path().with_name('mcp-oauth.key'))


def load_key(path):
    """The sealing key, made (32 random bytes, mode 600) if there's none yet."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        key = unb64(path.read_text().strip())
        if len(key) != 32:
            raise SystemExit(f'{path}: not a 32-byte key (delete it to make a new one)')
        return key
    key = os.urandom(32)
    with os.fdopen(fd, 'w') as f:
        f.write(b64(key) + '\n')
    return key


class Sealer:
    """JSON payloads, encrypted and authenticated, each for one purpose (the associated data)."""

    def __init__(self, key):
        self.key, self.aes = key, AESGCM(key)

    def seal(self, purpose, payload, ttl):
        body = {'exp': int(time.time()) + ttl if ttl else None, 'jti': secrets.token_urlsafe(12), 'd': payload}
        nonce = os.urandom(12)
        return b64(nonce + self.aes.encrypt(nonce, json.dumps(body, separators=(',', ':')).encode(), purpose.encode()))

    def unseal(self, blob, purpose):
        """(payload, jti, exp), or None: not ours, changed, for another purpose, or expired."""
        try:
            raw = unb64(blob or '')
            body = json.loads(self.aes.decrypt(raw[:12], raw[12:], purpose.encode()))
        except (ValueError, InvalidTag, TypeError):
            return None
        if not isinstance(body, dict) or (body.get('exp') is not None and body['exp'] < time.time()):
            return None
        return body.get('d'), str(body.get('jti')), body.get('exp')

    def mac(self, *parts):
        return b64(hmac.new(self.key, b'csrf\0' + '\0'.join(parts).encode(), hashlib.sha256).digest())


class Used:
    """One-time ids (codes, refresh tokens) already used, until they expire. In memory: after
    a restart a refresh token could be used once more (PKCE and 5 minutes cover codes)."""

    def __init__(self):
        self.ids = {}

    def use(self, jti, exp):
        now = time.time()
        if len(self.ids) > 10_000:
            self.ids = {k: v for k, v in self.ids.items() if v >= now}
        if jti in self.ids:
            return False
        self.ids[jti] = exp or now + 86400
        return True

    def __contains__(self, jti):
        return jti in self.ids


# --- redirect URIs, as kobo-mcp: https, loopback http (any port at /authorize, RFC 8252
# section 7.3: Claude Code picks one per run) and apps' own schemes; nothing script-like

LOOPBACK = {'localhost', '127.0.0.1', '::1'}
BAD_SCHEMES = {'javascript', 'data', 'vbscript', 'file', 'blob', 'about', 'ws', 'wss'}


def loopback(uri):
    parts = urlsplit(uri)
    return parts.scheme == 'http' and (parts.hostname or '') in LOOPBACK


def redirect_problem(uris):
    if not uris or len(uris) > 10:
        return 'Between 1 and 10 redirect_uris are needed.'
    for uri in uris:
        try:
            parts = urlsplit(uri)
            parts.port  # noqa: B018 - raises on a bad port
        except ValueError:
            return f'redirect_uri {uri!r} is not a valid URL.'
        scheme = parts.scheme.lower()
        if len(uri) > 1000 or '#' in uri:
            return f'redirect_uri {uri!r} is too long or has a fragment.'
        if scheme == 'https' and not parts.hostname:
            return f'redirect_uri {uri!r} has no host.'
        if scheme == 'http' and not loopback(uri):
            return f'redirect_uri {uri!r} uses http: only https, or http to this computer (localhost).'
        if not scheme or scheme in BAD_SCHEMES:
            return f'redirect_uri {uri!r} uses a scheme that isn\'t allowed.'
    return None


def without_port(uri):
    p = urlsplit(uri)
    return p.scheme, p.hostname, p.path or '/', p.query


def redirect_matches(uri, registered):
    if uri in registered:
        return True
    return loopback(uri) and any(loopback(r) and without_port(r) == without_port(uri) for r in registered)


class Client(OAuthClientInformationFull):
    def validate_redirect_uri(self, redirect_uri):
        registered = [str(u) for u in self.redirect_uris or []]
        if redirect_uri is None:
            if len(registered) == 1:
                return AnyUrl(registered[0])
            raise InvalidRedirectUriError('redirect_uri must be given: the client has more than one')
        if not redirect_matches(str(redirect_uri), registered):
            raise InvalidRedirectUriError(f"Redirect URI '{redirect_uri}' not registered for client")
        return redirect_uri


class Code(AuthorizationCode):
    jti: str


class Refresh(RefreshToken):
    jti: str


def cid(client_id):
    """Codes and tokens carry a hash of the (long, sealed) client id."""
    return hashlib.sha256(client_id.encode()).hexdigest()[:32]


def espo_sign_in(espo_url, username, password, code=''):
    """EspoCRM's own check of a sign-in: (result, userName). result is 'admin', 'not admin',
    'refused' (username, password or code), 'code' (a two-factor code is needed) or
    'unreachable'. The session EspoCRM makes for it is ended at once."""
    api = espo_url.rstrip('/') + '/api/v1'
    headers = {'Espo-Authorization': base64.b64encode(f'{username}:{password}'.encode()).decode(),
               'Espo-Authorization-By-Token': 'false'}
    if code:
        headers['Espo-Authorization-Code'] = code
    try:
        with urllib.request.urlopen(urllib.request.Request(api + '/App/user', headers=headers), timeout=20) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 401 and e.headers.get('X-Status-Reason') == 'second-step-required' and not code:
            return 'code', None
        return ('refused' if e.code in (401, 403) else 'unreachable'), None
    except (urllib.error.URLError, OSError, ValueError):
        return 'unreachable', None
    user = body.get('user') or {}
    name = user.get('userName') or username
    if body.get('token'):
        token_auth = {'Espo-Authorization': base64.b64encode(f'{name}:{body["token"]}'.encode()).decode(),
                      'Espo-Authorization-By-Token': 'true', 'Content-Type': 'application/json'}
        try:
            urllib.request.urlopen(urllib.request.Request(
                api + '/App/destroyAuthToken', method='POST', headers=token_auth,
                data=json.dumps({'token': body['token']}).encode()), timeout=20).close()
        except (urllib.error.URLError, OSError):
            pass  # it expires by itself
    ok = user.get('type') in ADMIN_TYPES and user.get('isActive', True)
    return ('admin' if ok else 'not admin'), name


class Provider:
    """The SDK's OAuthAuthorizationServerProvider, and its token check (keys too)."""

    def __init__(self, admins, key_verifier, public_url, espo_url, espo_site_url, sealer):
        self.admins, self.key_verifier, self.sealer = admins, key_verifier, sealer
        self.espo_url, self.espo_site_url = espo_url, espo_site_url
        self.public_url = public_url.rstrip('/')
        self.resource = self.public_url + '/mcp'
        self.used = Used()

    # clients (RFC 7591): the client id is the sealed registration
    async def register_client(self, client_info):
        uris = [str(u) for u in client_info.redirect_uris or []]
        problem = redirect_problem(uris)
        if problem:
            raise RegistrationError('invalid_redirect_uri', problem)
        name = (client_info.client_name or '').strip()[:100] or None
        client_info.client_id = self.sealer.seal(CLIENT, {
            'n': name, 'r': uris, 'm': client_info.token_endpoint_auth_method, 's': client_info.client_secret,
            'g': client_info.grant_types, 'sc': client_info.scope, 't': client_info.client_id_issued_at}, None)
        client_info.client_name = name

    async def get_client(self, client_id):
        opened = self.sealer.unseal(client_id, CLIENT)
        if not opened or not isinstance(opened[0], dict):
            return None
        d = opened[0]
        try:
            return Client(client_id=client_id, client_name=d.get('n'), redirect_uris=d['r'],
                          token_endpoint_auth_method=d.get('m'), client_secret=d.get('s'),
                          grant_types=d.get('g') or ['authorization_code', 'refresh_token'], scope=d.get('sc'),
                          client_id_issued_at=d.get('t'), client_secret_expires_at=0 if d.get('s') else None)
        except (KeyError, ValueError):
            return None

    # /authorize: to the sign-in page
    async def authorize(self, client, params):
        if params.resource and params.resource.rstrip('/') != self.resource:
            raise AuthorizeError('invalid_target', f'This server only issues tokens for {self.resource}.')
        pending = self.sealer.seal(PENDING, {
            'c': client.client_id, 'r': str(params.redirect_uri), 'x': params.redirect_uri_provided_explicitly,
            'cc': params.code_challenge, 'st': params.state, 'sc': params.scopes or []}, PENDING_TTL)
        return f'{self.public_url}/login?p={pending}'

    def issue_code(self, pending, user):
        return self.sealer.seal(CODE, {**pending, 'c': cid(pending['c']), 'u': user}, CODE_TTL)

    async def load_authorization_code(self, client, authorization_code):
        opened = self.sealer.unseal(authorization_code, CODE)
        if not opened:
            return None
        d, jti, exp = opened
        if d.get('c') != cid(client.client_id) or jti in self.used:
            return None
        return Code(code=jti, scopes=d.get('sc') or [], expires_at=float(exp), client_id=client.client_id,
                    code_challenge=d['cc'], redirect_uri=AnyUrl(d['r']), redirect_uri_provided_explicitly=bool(d['x']),
                    resource=self.resource, subject=d['u'], jti=jti)

    async def exchange_authorization_code(self, client, authorization_code):
        if not self.used.use(authorization_code.jti, authorization_code.expires_at):
            raise TokenError('invalid_grant', 'authorization code has already been used')
        return self.tokens(client.client_id, authorization_code.subject, authorization_code.scopes)

    async def load_refresh_token(self, client, refresh_token):
        opened = self.sealer.unseal(refresh_token, REFRESH)
        if not opened:
            return None
        d, jti, exp = opened
        if d.get('c') != cid(client.client_id) or jti in self.used:
            return None
        return Refresh(token=jti, client_id=client.client_id, scopes=d.get('sc') or [], expires_at=exp,
                       resource=self.resource, subject=d['u'], jti=jti)

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        if not await anyio.to_thread.run_sync(self.admins.is_admin, refresh_token.subject):
            raise TokenError('invalid_grant', f'{refresh_token.subject} is no longer an active EspoCRM admin.')
        if not self.used.use(refresh_token.jti, refresh_token.expires_at):
            raise TokenError('invalid_grant', 'refresh token has already been used')
        return self.tokens(client.client_id, refresh_token.subject, scopes or refresh_token.scopes)

    def tokens(self, client_id, user, scopes):
        payload = {'c': cid(client_id), 'u': user, 'sc': scopes}
        return OAuthToken(access_token=self.sealer.seal(ACCESS, payload, ACCESS_TTL), token_type='Bearer',
                          expires_in=ACCESS_TTL, refresh_token=self.sealer.seal(REFRESH, payload, REFRESH_TTL),
                          scope=' '.join(scopes) or None)

    # the bearer on /mcp: a key (keys.py), or an access token
    async def load_access_token(self, token):
        if token.startswith(keys.PREFIX):
            return await self.key_verifier.verify_token(token)
        opened = self.sealer.unseal(token, ACCESS)
        if not opened:
            return None
        d, jti, exp = opened
        if not d.get('u') or not await anyio.to_thread.run_sync(self.admins.is_admin, d['u']):
            return None
        # never the bearer itself in token: AccessToken reprs would show it
        return AccessToken(token=f'oauth:{jti}', client_id=str(d.get('c')), scopes=d.get('sc') or [],
                           expires_at=exp, resource=self.resource, subject=d['u'])

    async def verify_token(self, token):
        return await self.load_access_token(token)

    async def revoke_token(self, token):
        """Not offered (tokens are stateless): see the module's docstring for ending sessions."""


# --- the sign-in page --------------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in to EspoCRM</title><style nonce="{nonce}">
body {{ font: 16px/1.5 system-ui, sans-serif; background: #f4f5f7; color: #1d2433; margin: 0; }}
main {{ max-width: 26rem; margin: 3rem auto; background: #fff; padding: 2rem; border-radius: 8px;
       box-shadow: 0 1px 3px rgba(0,0,0,.12); }}
h1 {{ font-size: 1.3rem; margin: 0 0 1rem; }}
label {{ display: block; font-weight: 600; margin: 1rem 0 .25rem; }}
input {{ width: 100%; box-sizing: border-box; padding: .5rem; font: inherit; border: 1px solid #b8bfcc; border-radius: 4px; }}
button {{ margin-top: 1.5rem; width: 100%; padding: .6rem; font: inherit; font-weight: 600; color: #fff;
         background: #2f5fb3; border: 0; border-radius: 4px; cursor: pointer; }}
.hint, .small {{ color: #5b6475; font-size: .9rem; }}
.error {{ background: #fdecea; color: #8a1c13; padding: .6rem .8rem; border-radius: 4px; margin-bottom: 1rem; }}
</style></head><body><main>{body}</main></body></html>"""


def headers(nonce, redirect_uri=None):
    # Chrome applies form-action to the redirect after the post: the client's origin too
    target = ''
    if redirect_uri:
        p = urlsplit(redirect_uri)
        target = f' {p.scheme}://{p.netloc}' if p.scheme in ('http', 'https') else f' {p.scheme}:'
    return {'Content-Security-Policy': f"default-src 'none'; style-src 'nonce-{nonce}'; form-action 'self'{target}; "
                                       "frame-ancestors 'none'; base-uri 'none'",
            'X-Frame-Options': 'DENY', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
            'Cache-Control': 'no-store'}


class Limiter:
    def __init__(self, limit=ATTEMPTS, window=ATTEMPTS_WINDOW):
        self.limit, self.window, self.hits = limit, window, {}

    def allow(self, key):
        now = time.monotonic()
        if len(self.hits) > 10_000:
            self.hits = {k: v for k, v in self.hits.items() if v and v[-1] > now - self.window}
        hits = self.hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


EXPIRED = "This sign-in link has expired or isn't valid. Start connecting again from your app."
MESSAGES = {
    'refused': "EspoCRM didn't accept that username and password (or two-factor code).",
    'code': 'Your account uses two-factor authentication: type your password again, and the code.',
    'not admin': 'Only EspoCRM administrators can connect: this MCP changes fields and roles for the whole '
                 'instance. Ask an administrator.',
    'unreachable': "Couldn't reach EspoCRM to check. Try again in a minute.",
    'busy': 'Too many sign-in attempts. Wait a few minutes and try again.',
    'form': 'This form expired or came from another page. Start connecting again from your app.',
}


class SignIn:
    """/login (the form) and /login/callback (its post)."""

    def __init__(self, provider, env=os.environ):
        self.provider, self.sealer = provider, provider.sealer
        self.ip_header = env.get('MCP_CLIENT_IP_HEADER', '')
        self.by_ip, self.by_user = Limiter(), Limiter()
        self.path = urlsplit(provider.public_url).path.rstrip('/')
        self.secure = provider.public_url.startswith('https://')

    def pending(self, blob):
        opened = self.sealer.unseal(blob, PENDING)
        return opened[0] if opened and isinstance(opened[0], dict) else None

    def address(self, request):
        if self.ip_header:
            value = request.headers.get(self.ip_header, '').split(',')[0].strip()
            if value:
                return value
        return request.client.host if request.client else '-'

    def page(self, body, status=200, redirect_uri=None, cookie=None):
        nonce = secrets.token_urlsafe(12)
        response = HTMLResponse(PAGE.format(nonce=nonce, body=body), status_code=status,
                                headers=headers(nonce, redirect_uri))
        if cookie:
            response.set_cookie(COOKIE, cookie, max_age=PENDING_TTL, path=self.path + '/login', secure=self.secure,
                                httponly=True, samesite='strict')
        return response

    def message(self, key, status):
        return self.page(f'<div class="error">{html.escape(MESSAGES.get(key, key))}</div>', status)

    async def form(self, blob, pending, nonce, username='', error=None, status=200):
        client = await self.provider.get_client(pending['c'])
        name = (client.client_name if client else None) or 'An MCP client'
        back = urlsplit(pending['r']).netloc or pending['r']
        site = urlsplit(self.provider.espo_site_url).netloc
        e = html.escape
        body = f"""<h1>Sign in to EspoCRM</h1>
<p><b>{e(name)}</b> wants to connect Kobo forms to <b>{e(site)}</b> as you. You'll be sent back to <b>{e(back)}</b>.</p>
{f'<div class="error">{e(MESSAGES[error])}</div>' if error else ''}
<form method="post" action="{e(self.path)}/login/callback">
<input type="hidden" name="p" value="{e(blob)}"><input type="hidden" name="csrf" value="{e(self.sealer.mac(nonce, blob))}">
<label for="username">EspoCRM username</label>
<input id="username" name="username" autocomplete="username" required maxlength="100" value="{e(username)}"{'' if username else ' autofocus'}>
<label for="password">Password</label>
<input id="password" name="password" type="password" autocomplete="current-password" required maxlength="200"{' autofocus' if username else ''}>
<label for="code">Two-factor code <span class="hint">(if you use one)</span></label>
<input id="code" name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="20">
<button type="submit">Sign in</button></form>
<p class="small">EspoCRM checks your password; it isn't kept. Only administrators can connect. To disconnect,
remove the connector in your app; taking away someone's admin rights in EspoCRM ends theirs.</p>"""
        return self.page(body, status, pending['r'], cookie=nonce)

    async def login(self, request):
        blob = request.query_params.get('p', '')
        pending = self.pending(blob)
        if pending is None:
            return self.message(EXPIRED, 400)
        return await self.form(blob, pending, request.cookies.get(COOKIE) or secrets.token_urlsafe(16))

    async def callback(self, request):
        form = await request.form()
        blob, csrf = str(form.get('p', '')), str(form.get('csrf', ''))
        username, password = str(form.get('username', '')).strip()[:100], str(form.get('password', ''))[:200]
        code = ''.join(str(form.get('code', '')).split())[:20]
        pending = self.pending(blob)
        if pending is None:
            return self.message(EXPIRED, 400)
        nonce = request.cookies.get(COOKIE, '')
        if not nonce or not hmac.compare_digest(csrf, self.sealer.mac(nonce, blob)):
            return self.message('form', 400)
        if not username or not password:
            return await self.form(blob, pending, nonce, username, 'refused', 400)
        if not self.by_ip.allow(self.address(request)) or not self.by_user.allow(username.lower()):
            return self.message('busy', 429)
        result, user = await anyio.to_thread.run_sync(espo_sign_in, self.provider.espo_url, username, password, code)
        if result != 'admin':
            return await self.form(blob, pending, nonce, username, result, 400 if result != 'unreachable' else 503)
        target = construct_redirect_uri(pending['r'], code=self.provider.issue_code(pending, user),
                                        state=pending.get('st'))
        response = RedirectResponse(target, status_code=303, headers={'Cache-Control': 'no-store',
                                                                      'Referrer-Policy': 'no-referrer'})
        response.delete_cookie(COOKIE, path=self.path + '/login')
        return response
