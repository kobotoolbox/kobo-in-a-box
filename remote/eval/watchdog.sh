#!/usr/bin/env bash
# Babysits a benchmark batch ON THE GPU DROPLET (MODELS-PLAN.md phase 1 and its follow-ups,
# which write /root/followup.done when finished): every minute, if the running
# smoke-tests log hasnt grown for STALL minutes, or the recipe has run longer than
# MAX minutes, stop that smoke-test (the batch records it as failed and moves on; failed
# recipes are rerun once at the end). Ends when the follow-ups are done.
STALL=${STALL:-15} MAX=${MAX:-45}
log() { echo "$(date -u +%FT%TZ) $*" >> /root/watchdog.log; }
log "watchdog started (stall ${STALL} min, max ${MAX} min per recipe)"
while [ ! -f /root/followup.done ]; do
    # the benchmark: started by gpu-tiers.sh as "python3 -I smoke-test.py", in /root/kobo-box-ai
    pid=$(ps -eo pid=,args= | awk "\$2==\"python3\" && \$3==\"-I\" && \$4==\"smoke-test.py\" {print \$1}" | head -1)
    if [ -n "$pid" ]; then
        recipe=$(tr "\0" "\n" < /proc/$pid/environ 2>/dev/null | sed -n "s/^BENCH_RECIPE=//p")
        f=/root/kobo-box-ai/results/log-$recipe.txt
        age=$(( ( $(date +%s) - $(stat -c %Y "$f" 2>/dev/null || date +%s) ) / 60 ))
        ran=$(( $(ps -o etimes= -p "$pid" | tr -d " ") / 60 ))
        if [ "$age" -ge "$STALL" ] || [ "$ran" -ge "$MAX" ]; then
            log "stopping $recipe (pid $pid): log idle ${age} min, running ${ran} min"
            kill "$pid"; sleep 10; kill -9 "$pid" 2>/dev/null
        fi
    fi
    sleep 60
done
log "follow-ups done; watchdog ends"
