#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMPS_DIR="${ROOT_DIR}/dumps"
STAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
OUTFILE="${DUMPS_DIR}/pokeprice-data-${STAMP}.sql"
OUTFILE_GZ="${OUTFILE}.gz"

mkdir -p "${DUMPS_DIR}"

echo "[dump] Writing data-only dump to ${OUTFILE}"
docker compose exec -T postgres pg_dump \
  -U pokeprice \
  -d pokeprice \
  --data-only \
  --no-owner \
  --no-acl \
  --table=price_points \
  --table=card_scrape_state \
  --table=scrape_runs > "${OUTFILE}"

gzip -f "${OUTFILE}"

echo "[dump] Done: ${OUTFILE_GZ}"
