#!/usr/bin/env bash
# The knowledge base on the box (W10): search over the offline library's documentation,
# for the agent (MCP at http://knowledge.kobo.local/mcp). Run ON THE BOX / DROPLET in
# /root/kobo-box-ai/knowledge.
#
#   ./knowledge.sh build          the image and the embedding model (online, on the rig;
#                                 boxes get both, and the index, from the content pack)
#   ./knowledge.sh index [--full] [--collection <id>]  build or refresh the index from the
#                                 library's pages (collections.json); restarts the search
#   ./knowledge.sh up             start it (the index must exist)
#   ./knowledge.sh down | logs | status
#   ./knowledge.sh search <question...>   the best sections, as the agent gets them
#   ./knowledge.sh eval [report.json]     retrieval checks (eval.py, cases/)
#   ./knowledge.sh cases <kobo-support-bot-poc checkout>  copy in the support bot's cases
#                                 (a private repo: not in git here), then build again
#
# Settings are in knowledge.env (knowledge.local.env, not in git, overrides them).
set -euo pipefail
cd "$(dirname "$0")"
set -a; source knowledge.env; [[ -f knowledge.local.env ]] && source knowledge.local.env; set +a

compose() { docker compose -p kobo-knowledge -f docker-compose.knowledge.yml "$@"; }

wait_ready() {
    for _ in $(seq 60); do
        curl -fsS -m 5 -o /dev/null "http://127.0.0.1:$KNOWLEDGE_PORT/healthz" 2>/dev/null && return 0
        sleep 2
    done
    echo "the knowledge base isn't answering on :$KNOWLEDGE_PORT (./knowledge.sh logs)" >&2; return 1
}

library_link() {  # on|off: the service flag the landing page and status page read
    [[ -d "$LIBRARY_DIR" ]] || return 0
    mkdir -p "$LIBRARY_DIR/.services"
    if [[ $1 == on ]]; then touch "$LIBRARY_DIR/.services/knowledge"; else rm -f "$LIBRARY_DIR/.services/knowledge"; fi
}

case "${1:-}" in
    build)
        docker build -q -t "$KNOWLEDGE_IMAGE" . >/dev/null
        docker pull -q "$EMBED_IMAGE" >/dev/null
        file=${EMBED_DOWNLOAD#*:}
        if [[ ! -s "$MODELS_DIR/$file" ]]; then
            curl -fsSL --retry 3 -o "$MODELS_DIR/$file.part" \
                "https://huggingface.co/${EMBED_DOWNLOAD%%:*}/resolve/main/$file"
            mv "$MODELS_DIR/$file.part" "$MODELS_DIR/$file"
        fi
        echo "built $KNOWLEDGE_IMAGE; $EMBED_MODEL in $MODELS_DIR"
        ;;
    index)
        shift
        install -d -m 755 "$KNOWLEDGE_DIR"
        compose up -d --wait embed
        compose --profile index run --rm -T index python index.py "$@"
        chmod 644 "$KNOWLEDGE_DIR/knowledge.db"
        # The search holds the index in memory: start it on the new one
        if [[ -n "$(compose ps -q knowledge)" ]]; then compose up -d --force-recreate knowledge; wait_ready; fi
        ;;
    up)
        [[ -s "$KNOWLEDGE_DIR/knowledge.db" ]] || { echo "no index in $KNOWLEDGE_DIR: './knowledge.sh index' (or the content pack)" >&2; exit 1; }
        compose up -d --wait embed
        # Recreated: it reads the index at start, and an update may have replaced it
        compose up -d --wait --force-recreate knowledge
        wait_ready
        library_link on
        echo "knowledge base on http://knowledge.kobo.local/mcp: $(curl -fsS "http://127.0.0.1:$KNOWLEDGE_PORT/healthz")"
        ;;
    down) compose down; library_link off ;;
    logs) compose logs -f --tail 100 ;;
    status) compose ps ;;
    search)
        shift
        compose exec -T knowledge python -c 'import sys, server; print(server.search_knowledge(" ".join(sys.argv[1:])))' "$@"
        ;;
    eval)
        out=${2:-}
        if [[ -n "$out" ]]; then
            compose exec -T knowledge python eval.py --out /tmp/eval.json
            compose cp knowledge:/tmp/eval.json "$out"
        else
            compose exec -T knowledge python eval.py
        fi
        ;;
    cases)
        src=${2:?usage: $0 cases <kobo-support-bot-poc checkout>}
        mkdir -p cases/support-bot
        for f in howto multilingual unanswerable hallucination_bait; do
            cp "$src/backend/evals/cases/$f.yaml" cases/support-bot/
        done
        echo "copied $(git -C "$src" log -1 --format='%h %cs' 2>/dev/null || echo '?') cases into cases/support-bot/"
        ;;
    *) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1 ;;
esac
