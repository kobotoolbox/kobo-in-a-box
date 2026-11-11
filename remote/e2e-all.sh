#!/usr/bin/env bash
# Every end-to-end test that runs on one box, one after another, as the e2e user
# (password in /root/e2e-user.pw, token in /root/e2e-token). Run ON THE RIG or a box, with
# ./offline.sh on, after the parts are up:
#
#   /root/kobo-box-ai/e2e-all.sh [test ...]     default: all of them, in the order below
#
# Each test's output goes to results/suite-<time>/<test>.log; the summary (PASS / FAIL and
# the log's last line) to results/suite-<time>/summary.txt. Syncing needs two boxes
# (sync/README.md); the benchmark (smoke-test.py) runs separately.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$HERE/results/suite-$(date +%Y%m%d-%H%M%S)
mkdir -p "$OUT"
PW=$(cat /root/e2e-user.pw)
HOSTS=(--add-host kobo.local:127.0.0.1 --add-host kf.kobo.local:127.0.0.1 --add-host kc.kobo.local:127.0.0.1
       --add-host ee.kobo.local:127.0.0.1 --add-host dash.kobo.local:127.0.0.1 --add-host mcp.kobo.local:127.0.0.1
       --add-host maps.kobo.local:127.0.0.1 --add-host cases.kobo.local:127.0.0.1)
in_mcp() {  # a test script in the kobo-mcp image, with the e2e token
    local script=$1; shift
    docker run --rm --network host -e KOBO_TOKEN="$(cat /root/e2e-token)" "${HOSTS[@]}" \
        -v /opt/maps:/opt/maps:ro -v "$script:/e2e.py:ro" --entrypoint python kobo-mcp:box /e2e.py "$@"
}

t_nlp()        { python3 -I "$HERE/e2e-nlp.py" e2e "$PW"; }
t_signin()     { "$HERE/e2e-signin.sh"; }
t_users()      { "$HERE/e2e-users.sh"; }
t_cases()      { python3 -I "$HERE/espocrm/e2e-espo.py" --edge; }
t_cases_ledger()   { python3 -I "$HERE/espocrm/e2e-espo.py" --edge --ledger; }
t_cases_edits()    { python3 -I "$HERE/espocrm/e2e-espo.py" --edge --edits; }
t_cases_followup() {  # the bridge refreshes open_cases.csv every 20 s for it, then as before
    local env=/etc/kobo-box/espocrm.env had; had=$(cat "$env" 2>/dev/null || true)
    { [[ -n "$had" ]] && echo "$had"; echo BRIDGE_LIST_MIN_SECONDS=20; } > "$env"
    "$HERE/espocrm/espocrm.sh" up >/dev/null
    python3 -I "$HERE/espocrm/e2e-espo.py" --edge --followup; local rc=$?
    if [[ -n "$had" ]]; then echo "$had" > "$env"; else rm -f "$env"; fi
    "$HERE/espocrm/espocrm.sh" up >/dev/null
    return $rc
}
t_cases_mcp()  { set -a; source /root/espocrm.secrets; set +a
                 docker run --rm --network kobo-assistant -e CASES_MCP_TOKEN -v "$HERE/espocrm/cases-mcp-check.py:/c.py:ro" \
                     --entrypoint python kobo-mcp:box /c.py http://cases-mcp:8090/mcp; }
t_dash()       { in_mcp "$HERE/dash/e2e-dash.py"; }
t_dash_espo()  {  # the dashboards' EspoCRM feeds: an API user made with EspoCRM's admin password
    set -a; source /root/espocrm.secrets; set +a
    docker run --rm --network host -e KOBO_TOKEN="$(cat /root/e2e-token)" -e ESPO_ADMIN_PASSWORD "${HOSTS[@]}" \
        -v "$HERE/dash:/dash:ro" --entrypoint python kobo-mcp:box /dash/e2e-dash-espo.py
}
t_maps()       { in_mcp "$HERE/maps/e2e-maps.py"; }
t_maps_dash()  { in_mcp "$HERE/maps/e2e-maps.py" --dashboard; }
t_mcp()        { bash "$HERE/agents/run-mcp-check.sh" /root/kobo-mcp-src /root/e2e-token; }
t_agent_permissions() {  # OpenCode on w4-permissions.py's stand-in model, then back
    printf 'AGENT_LLM_URL=http://mcp.kobo.local:8099/v1\n' > "$HERE/agents/agents.local.env"
    "$HERE/agents/agents.sh" up >/dev/null
    (cd "$HERE/agents" && python3 -I w4-permissions.py); local rc=$?
    rm -f "$HERE/agents/agents.local.env"; "$HERE/agents/agents.sh" up >/dev/null
    return $rc
}
t_knowledge()  { "$HERE/knowledge/knowledge.sh" eval; }
t_paper()      { "$HERE/paper/paper.sh" e2e; }
t_collect()    { "$HERE/phone.sh" up && "$HERE/e2e-collect.sh"; }

ALL=(nlp signin users cases cases_ledger cases_edits cases_followup cases_mcp dash dash_espo maps maps_dash
     mcp agent_permissions knowledge paper collect)
for t in "${@:-${ALL[@]}}"; do
    start=$(date +%s)
    if "t_$t" > "$OUT/$t.log" 2>&1; then result=PASS; else result=FAIL; fi
    line="$(printf '%-18s %s %4ss  %s' "$t" "$result" "$(( $(date +%s) - start ))" "$(grep -v '^\s*$' "$OUT/$t.log" | tail -1 | cut -c1-110)")"
    echo "$line" | tee -a "$OUT/summary.txt"
done
echo "logs in $OUT"
