#!/usr/bin/env bash
set -euo pipefail

if [[ "${CONFIRM:-}" != "yes" ]]; then
  echo "Refusing to run without CONFIRM=yes (destructive bootstrap flow)."
  echo "Usage: CONFIRM=yes DUMP_FILE=/abs/path/to/pokeprice-data-<UTC>.sql[.gz] ./scripts/prod_bootstrap.sh"
  exit 1
fi

if [[ -z "${DUMP_FILE:-}" ]]; then
  echo "DUMP_FILE is required."
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f "${DUMP_FILE}" ]]; then
  echo "Dump file not found: ${DUMP_FILE}"
  exit 1
fi

TMP_SQL=""
cleanup() {
  if [[ -n "${TMP_SQL}" && -f "${TMP_SQL}" ]]; then
    rm -f "${TMP_SQL}"
  fi
}
trap cleanup EXIT

if [[ "${DUMP_FILE}" == *.gz ]]; then
  TMP_SQL="$(mktemp -t pokeprice-restore-XXXXXX.sql)"
  echo "[bootstrap] Decompressing ${DUMP_FILE} -> ${TMP_SQL}"
  gzip -dc "${DUMP_FILE}" > "${TMP_SQL}"
  RESTORE_FILE="${TMP_SQL}"
else
  RESTORE_FILE="${DUMP_FILE}"
fi

echo "[bootstrap] Running migrations"
make migrate

echo "[bootstrap] Seeding catalog sets/cards from YML"
make catalog-seed-sets
make catalog-seed-cards

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL must be set for psql restore."
  exit 1
fi

echo "[bootstrap] Restoring data dump into configured DATABASE_URL"
psql "${DATABASE_URL}" -f "${RESTORE_FILE}"

echo "[bootstrap] Refreshing materialized views"
uv run pokeprice-api refresh-mvs

echo "[bootstrap] Done."
