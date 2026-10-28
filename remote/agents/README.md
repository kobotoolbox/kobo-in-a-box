# Agent config for the box

`opencode.json` is the recommended OpenCode config for staff agents on the box (W3, used by
W4). It connects to the box's kobo-mcp and keeps the agent from changing Kobo data
without asking.

| Setting | What it does |
|---|---|
| `mcp.kobo` | kobo-mcp at `http://mcp.kobo.local/mcp`, signing in with OAuth (each user pastes their Kobo token once on its `/login` page; PLAN.md §3h) |
| `tools`: `kobo_delete_*` → `false` | The model never sees the delete tools. Kobo has no trash |
| `permission`: `kobo_*` → `ask`, then the 36 read-only tools → `allow` | Reads run freely; anything that changes Kobo (deploying, editing submissions, sharing, dashboards…) asks first. The last matching rule wins, so the catch-all comes first |
| `webfetch`, `websearch` → `deny` | The box is offline; this avoids slow timeouts |
| `autoupdate: false` | No update checks against the internet |

Pair it with kobo-mcp's server-side settings, which hold even if the client config changes:

```
EXTRA_KOBO_HOSTS=kf.kobo.local
HTTP_KOBO_HOSTS=kf.kobo.local        # the box's Kobo is plain http
CUSTOM_KOBO_SERVERS=false            # only the box's Kobo
TOOL_PROFILES=analysis,forms,data    # 32 tools, no deletes: ~15k tokens instead of ~38k
DASH_KOBO_HOSTS=kf.kobo.local        # if dashboards run on the box
# Leave RELAY_KEYS / RESEND_API_KEY unset: email needs the internet
```

**Unverified (check in W4 on the rig):** OpenCode's docs show `permission` keys as tool
names with wildcards, but only give examples for built-in tools. That the `kobo_*` rules
apply to MCP tools has to be tested. The `tools` map is documented for MCP tools, and
`TOOL_PROFILES` without `deletes` removes the delete tools on the server anyway.

The read-only list comes from the tools' `readOnlyHint` annotations in kobo-mcp. Regenerate
it when kobo-mcp gains tools.
