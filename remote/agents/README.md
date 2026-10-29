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

## Agents on the box (W4)

| File | What it is |
|---|---|
| `agents.env` | The agent model, its context and slots, where OpenCode reaches it, kobo-mcp's tool profile, OpenCode's version and password |
| `docker-compose.agents.yml` | `agent-llm` (profile `llm`: the agent model's own llama-server on :8083), `kobo-mcp` and `opencode` (profile `agents`) |
| `Dockerfile.opencode` | OpenCode (pinned) plus the analysis sandbox's basics (Python, pandas, matplotlib); its shell tools run here |
| `agents.sh` | `llm up\|down` on the GPU machine; `up\|down\|logs` for kobo-mcp + OpenCode; writes `opencode/opencode.json` from `opencode.json` plus the box's provider and kobo-mcp |
| `w4-fixture.py` | A household water survey with 63 seeded submissions and known answers (`results/w4-truth.json`), with 3 duplicates, 5 missing answers and 2 inconsistent records planted |
| `w4-tasks.json` | 30 tasks staff would ask, by category (discovery, counts, breakdowns, data quality, reading, exports, reports, forms, writes, safety), each with checks |
| `w4-run.py` | Runs each task as a fresh `opencode run --format json --auto` and scores it: Kobo tools used, answer contents, and Kobo's state afterwards |

Offline notes: OpenCode 1.19.5 bundles `@ai-sdk/openai-compatible` (an unbundled provider
would be installed from npm on first use); `small_model` is the box's model, or session
titles go to OpenCode's hosted service; `share` is disabled; the env turns off update
checks, the model catalogue fetch and LSP downloads. Recheck all of this offline when
OpenCode's version changes. `--auto` approves `ask` permissions but still enforces
`deny`, so the runner exercises writes and the delete refusals without a person.

### Test session on DigitalOcean (two droplets)

The CPU rig's snapshot already has Kobo, the `e2e` user and kobo-mcp's source, so the GPU
droplet only runs the agent model, reached over the region's private network.

```bash
# GPU droplet (fresh): bootstrap, then the agent model; let the CPU rig reach :8083
NAME=kobo-box-gpu SIZE=gpu-h100x1-80gb ./provision.sh            # SSH_PORT=443 if 22 is blocked
ssh root@<gpu> 'bash /root/kobo-box-ai/bootstrap.sh'               # + gpt-oss-120b, see gpu-tiers.sh
doctl compute firewall add-rules <kobo-box-gpu-fw> --inbound-rules "protocol:tcp,ports:8083,tag:kobo-box-ai"
ssh root@<gpu> '/root/kobo-box-ai/agents/agents.sh llm up'

# CPU rig (snapshot): Kobo on the new IP, then OpenCode + kobo-mcp pointed at the GPU
SIZE=s-8vcpu-32gb-amd ./provision.sh --from-snapshot
ssh root@<cpu> 'cd /root/kobo-install && python3 run.py; /root/kobo-box-ai/library/library.sh up'
#   set AGENT_LLM_URL=http://<gpu private ip>:8083/v1 in agents/agents.env, then
ssh root@<cpu> '/root/kobo-box-ai/agents/agents.sh up'
ssh root@<cpu> 'cd /root/kobo-box-ai/agents && python3 -I w4-fixture.py && python3 -I w4-run.py --label gemma-26b'

# Offline: no internet, but the private network to the model stays open
OFFLINE_KEEP=<vpc cidr> ./offline.sh on
```
