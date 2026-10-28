#!/usr/bin/env bash
# Runs inside python:3.12-bookworm with /root/kpi-src mounted at /src (see kpi-test.sh). Uses the KPI CI settings modules.
set -e
apt-get -qq update
DEBIAN_FRONTEND=noninteractive apt-get -qq -y install gdal-bin gettext libproj-dev \
    postgresql-client ffmpeg default-jre-headless gcc libc-dev build-essential >/dev/null
pip -q install --root-user-action=ignore uv
uv pip sync -q --system dependencies/pip/dev_requirements.txt
until pg_isready -q -h kpi-test-pg -U kobo; do sleep 2; done
for ds in testing testing_no_stripe; do
    echo "=== $ds"
    pytest --ds "kobo.settings.$ds" "$@" -ra -q -p no:cacheprovider -n 4 || true
done
