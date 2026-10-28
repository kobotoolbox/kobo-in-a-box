#!/usr/bin/env bash
# Run kobo-mcp's box check (W3) ON THE DROPLET: build kobo-mcp's image from a source tree
# (online, once), then start it in HTTP header mode with the box's settings and run
# mcp-check.py against it in the same container. Works offline once the image is built.
#
#   bash run-mcp-check.sh /root/kobo-mcp-src <token-file>
#
# The token file holds a regular Kobo user's API token (chmod 600); it's passed to the
# container as an env var and never printed.
set -euo pipefail
src=${1:?usage: $0 <kobo-mcp source dir> <token file>}
token_file=${2:?usage: $0 <kobo-mcp source dir> <token file>}
here=$(dirname "$(readlink -f "$0")")
box_ip=$(grep -o '"local_interface_ip": "[^"]*"' /root/kobo-install/.run.conf | cut -d'"' -f4)

docker image inspect kobo-mcp:box >/dev/null 2>&1 || docker build -q -t kobo-mcp:box "$src"

KOBO_TOKEN=$(cat "$token_file") docker run --rm \
  --add-host "kf.kobo.local:$box_ip" \
  -e KOBO_TOKEN \
  -e HOST=127.0.0.1 -e PORT=8080 \
  -e EXTRA_KOBO_HOSTS=kf.kobo.local -e HTTP_KOBO_HOSTS=kf.kobo.local \
  -e CUSTOM_KOBO_SERVERS=false -e TOOL_PROFILES=analysis,forms,data \
  -v "$here/mcp-check.py:/check/mcp-check.py:ro" \
  kobo-mcp:box sh -c '
    python -m kobo_mcp http > /tmp/server.log 2>&1 &
    for i in $(seq 30); do python -c "import urllib.request as u; u.urlopen(\"http://127.0.0.1:8080/healthz\")" 2>/dev/null && break; sleep 1; done
    python /check/mcp-check.py http://127.0.0.1:8080; status=$?
    grep -iE "error|traceback" /tmp/server.log | head -5
    exit $status'
