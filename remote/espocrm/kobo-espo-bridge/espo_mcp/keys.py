"""
MCP keys: one per EspoCRM admin, for header mode (`claude mcp add --header`).

    python3 -I espo_mcp/keys.py add <espo admin user>     prints a new key, once
    python3 -I espo_mcp/keys.py remove <espo admin user>
    python3 -I espo_mcp/keys.py list

The file (MCP_KEYS_FILE) keeps only each key's SHA-256 and its user, so a copy of it
can't be used to connect. A key works only while its user is an active EspoCRM admin:
that's checked on every call, so taking away someone's admin rights in EspoCRM also
takes away their key. Needs ESPO_URL and the admin password (ESPO_ADMIN_PASSWORD or in
BRIDGE_SECRETS), to check the user is an admin.
"""
import hashlib
import os
import secrets
import sys
import time
from pathlib import Path

PREFIX = 'kem_'  # kobo-espo MCP key: recognisable if pasted somewhere it shouldn't be


def path():
    return Path(os.environ.get('MCP_KEYS_FILE', '/state/mcp-keys'))


def hashed(key):
    return hashlib.sha256(key.strip().encode()).hexdigest()


def load():
    """{sha256: username}"""
    p = path()
    if not p.exists():
        return {}
    return dict(line.split(' ', 1) for line in p.read_text().split('\n') if ' ' in line)


def save(found):
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(''.join(f'{h} {u}\n' for h, u in found.items()))
    tmp.chmod(0o600)
    tmp.replace(p)


class Admins:
    """Who a key is, if they're still an active EspoCRM admin (checked at most every `ttl` s)."""

    def __init__(self, espo, ttl=60):
        self.espo, self.ttl, self.seen = espo, ttl, {}

    def is_admin(self, username):
        at, ok = self.seen.get(username, (0, False))
        if time.time() - at > self.ttl:
            user = self.espo.find('User', 'userName', username, select='userName,type,isActive')
            ok = bool(user and user.get('type') in ('admin', 'super-admin') and user.get('isActive'))
            self.seen[username] = (time.time(), ok)
        return ok

    def who(self, key):
        username = load().get(hashed(key)) if key and key.startswith(PREFIX) else None
        return username if username and self.is_admin(username) else None


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from espo_mcp.tools import admin_espo
    cmd, rest = (sys.argv[1] if len(sys.argv) > 1 else ''), sys.argv[2:]
    found = load()
    if cmd == 'list' and not rest:
        for user in sorted(found.values()):
            print(user)
        return
    if cmd not in ('add', 'remove') or len(rest) != 1:
        sys.exit(__doc__)
    username = rest[0]
    if cmd == 'remove':
        save({h: u for h, u in found.items() if u != username})
        print(f'keys of {username} removed')
        return
    if not Admins(admin_espo(os.environ)).is_admin(username):
        sys.exit(f'{username} is not an active EspoCRM admin: only admins get an MCP key')
    key = PREFIX + secrets.token_urlsafe(32)
    save({**found, hashed(key): username})
    print(key)


if __name__ == '__main__':
    main()
