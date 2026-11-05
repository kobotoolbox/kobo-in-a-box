#!/usr/bin/env bash
# Agents on the box (W4). Run ON THE BOX / DROPLET in /root/kobo-box-ai/agents.
#
#   ./agents.sh llm up|down      the agent model's llama-server (a GPU machine)
#   ./agents.sh up|down|logs     OpenCode (the Kobo machine), with the box's kobo-mcp
#                                from ../dash (./dash.sh up first)
#   ./agents.sh config           write opencode/opencode.json only
#
# Settings are in agents.env. OpenCode acts as the Kobo user whose API token is in
# KOBO_TOKEN_FILE (default /root/e2e-token); W4 still has to decide how each user's
# token reaches their session (PLAN, open question 1).
set -euo pipefail
cd "$(dirname "$0")"
set -a; source agents.env; set +a
# This machine's overrides, e.g. AGENT_LLM_URL for w4-permissions.py's stand-in model (never packed)
if [[ -f agents.local.env ]]; then set -a; source agents.local.env; set +a; fi
KOBO_TOKEN_FILE=${KOBO_TOKEN_FILE:-/root/e2e-token}

compose() { docker compose -p kobo-agents -f docker-compose.agents.yml "$@"; }

# OpenCode's config: the box's model, the box's kobo-mcp, and opencode.json's
# permissions (delete tools off, writes ask, reads allowed, web tools denied).
write_config() {
    mkdir -p opencode
    python3 - <<'PY'
import json, os
cfg = json.load(open('opencode.json'))
ctx = int(os.environ['AGENT_CTX']) // int(os.environ['AGENT_SLOTS'])
cfg['provider'] = {'box': {
    'npm': '@ai-sdk/openai-compatible',
    'name': 'Box agent model',
    'options': {'baseURL': os.environ['AGENT_LLM_URL']},
    'models': {'agent': {'name': os.environ['AGENT_MODEL'],
                         'limit': {'context': ctx, 'output': 8192}}},
}}
# small_model too: otherwise OpenCode sends session titles to its hosted service
cfg['model'] = cfg['small_model'] = 'box/agent'
cfg['share'] = 'disabled'
cfg['mcp'] = {'kobo': {
    'type': 'remote',
    'url': 'http://mcp.kobo.local/mcp',
    'enabled': True,
    'oauth': False,
    # Header mode: OAuth for MCP clients needs https (kobo-mcp's MCP_OAUTH), and would
    # open its sign-in in a browser on the box, not the user's
    'headers': {'X-Kobo-Token': '{env:KOBO_TOKEN}', 'X-Kobo-Base-URL': 'kf.kobo.local'},
    'timeout': 30000,
}}
# Case management's tools, when it runs on this box (espocrm.sh makes the token)
secrets = {}
try:
    secrets = dict(l.split('=', 1) for l in open(os.environ.get('ESPO_SECRETS', '/root/espocrm.secrets')).read().splitlines() if '=' in l)
except OSError:
    pass
if secrets.get('CASES_MCP_TOKEN'):
    cfg['mcp']['cases'] = {'type': 'remote', 'url': 'http://cases-mcp:8090/mcp', 'enabled': True,
                           'oauth': False, 'timeout': 30000,
                           'headers': {'Authorization': 'Bearer ' + secrets['CASES_MCP_TOKEN']}}
json.dump(cfg, open('opencode/opencode.json', 'w'), indent=2)
print('wrote opencode/opencode.json for', os.environ['AGENT_MODEL'], 'at', os.environ['AGENT_LLM_URL'])
PY
}

wait_for() {  # wait_for URL [seconds]
    for _ in $(seq "${2:-600}"); do
        curl -fsS -o /dev/null -u "opencode:$OPENCODE_SERVER_PASSWORD" "$1" 2>/dev/null && return 0
        sleep 1
    done
    echo "$1 not answering" >&2; return 1
}

case "${1:-}" in
    llm)
        case "${2:-}" in
            up) compose --profile llm up -d agent-llm
                wait_for http://localhost:8083/health 1200
                echo "agent model ready on :8083 ($AGENT_MODEL, ctx $AGENT_CTX, $AGENT_SLOTS slot(s))" ;;
            down) compose --profile llm down ;;
            *) echo "usage: $0 llm up|down" >&2; exit 1 ;;
        esac ;;
    config) write_config ;;
    up)
        write_config
        export KOBO_TOKEN; KOBO_TOKEN=$(cat "$KOBO_TOKEN_FILE")
        curl -fsS -o /dev/null -H 'Host: mcp.kobo.local' http://127.0.0.1/healthz \
            || { echo "kobo-mcp isn't answering at mcp.kobo.local: run ../dash/dash.sh up" >&2; exit 1; }
        docker network inspect kobo-assistant >/dev/null 2>&1 || docker network create kobo-assistant >/dev/null
        # Recreate, so OpenCode reads the config just written (it reads it only at start)
        compose --profile agents up -d --build --force-recreate --remove-orphans
        wait_for http://localhost:4096/ 180
        echo "OpenCode on 127.0.0.1:4096 (model at $AGENT_LLM_URL; kobo-mcp at mcp.kobo.local)" ;;
    down) compose --profile agents down ;;
    logs) compose --profile agents logs -f --tail 100 ;;
    *) echo "usage: $0 llm up|down | up | down | logs | config" >&2; exit 1 ;;
esac
