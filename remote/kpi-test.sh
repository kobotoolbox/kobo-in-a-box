#!/usr/bin/env bash
# KPI tests against /root/kpi-src, set up like the KPI CI workflow
# (.github/workflows/pytest.yml): PostGIS + Redis containers, dev requirements, a JRE.
# Run ON THE DROPLET with the branch checked out in /root/kpi-src (see STATUS.md):
#   bash /root/kobo-box-ai/kpi-test.sh [pytest paths...]   default: kobo/apps/subsequences/
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
paths=("${@:-kobo/apps/subsequences/}")
docker network inspect kpi-test >/dev/null 2>&1 || docker network create kpi-test >/dev/null
docker rm -f kpi-test-pg kpi-test-redis >/dev/null 2>&1 || true
docker run -d --name kpi-test-pg --network kpi-test -e POSTGRES_USER=kobo -e POSTGRES_PASSWORD=kobo -e POSTGRES_DB=kpi_test postgis/postgis:14-3.4 >/dev/null
docker run -d --name kpi-test-redis --network kpi-test redis:6.2 >/dev/null
docker run --rm --network kpi-test -v /root/kpi-src:/src -v "$here/kpi-test-inner.sh:/kpi-test-inner.sh:ro" -w /src \
  -e DATABASE_URL=postgis://kobo:kobo@kpi-test-pg:5432/kpi_test \
  -e "DJANGO_LANGUAGE_CODES=ar cs de-DE en es fr hi ku pl pt tr zh-hans" \
  -e DJANGO_SECRET_KEY=notSecretJustForTestingYep \
  -e DJANGO_SETTINGS_MODULE=kobo.settings.testing \
  -e REDIS_SESSION_URL=redis://kpi-test-redis:6379/2 -e CACHE_URL=redis://kpi-test-redis:6379/3 \
  -e ENKETO_REDIS_MAIN_URL=redis://kpi-test-redis:6379/0 -e CELERY_BROKER_URL=redis://kpi-test-redis:6379/1 \
  -e KOBOCAT_MEDIA_ROOT=/tmp/test_media -e KOBOCAT_URL=http://kobocat -e KOBOCAT_INTERNAL_URL=http://kobocat \
  -e KOBOFORM_URL=http://kpi -e SKIP_TESTS_WITH_CONCURRENCY=True \
  python:3.12-bookworm bash /kpi-test-inner.sh "${paths[@]}"
docker rm -f kpi-test-pg kpi-test-redis >/dev/null
