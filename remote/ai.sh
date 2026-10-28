#!/usr/bin/env bash
# Start/stop the local inference services.
#
#   ./ai.sh up gpu|cpu    (re)start with current ai.env
#   ./ai.sh down
#   ./ai.sh logs
set -euo pipefail
cd "$(dirname "$0")"
set -a; source ai.env; set +a

# Join the kobo-docker frontend network if Kobo is installed; otherwise use a
# standalone network so the models can be tested before Kobo is set up.
KOBO_NETWORK=$(docker network ls --format '{{.Name}}' | grep -m1 'kobo-fe-network' || true)
if [[ -z "$KOBO_NETWORK" ]]; then
    KOBO_NETWORK=kobo-ai
    docker network inspect "$KOBO_NETWORK" >/dev/null 2>&1 || docker network create "$KOBO_NETWORK" >/dev/null
fi
export KOBO_NETWORK

compose() { docker compose -p kobo-ai -f docker-compose.ai.yml --profile gpu --profile cpu "$@"; }

case "${1:-}" in
    up)
        profile=${2:?usage: $0 up gpu|cpu}
        compose down --remove-orphans
        docker compose -p kobo-ai -f docker-compose.ai.yml --profile "$profile" up -d
        echo "Network: $KOBO_NETWORK. Waiting for LLM to load..."
        until curl -fsS localhost:8081/health >/dev/null 2>&1; do sleep 3; done
        echo "LLM ready ($LLM_MODEL); whisper on :8082 ($WHISPER_MODEL)"
        ;;
    down) compose down --remove-orphans ;;
    logs) compose logs -f --tail 100 ;;
    *) echo "usage: $0 up gpu|cpu | down | logs" >&2; exit 1 ;;
esac
