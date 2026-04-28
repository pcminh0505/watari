.PHONY: up down test lint format migrate \
        catalog-seed-sets catalog-bootstrap catalog-seed-cards catalog-verify \
        scrape-cardrush scrape-snkrdunk \
        api api-dev \
        web-install web-dev web-build web-preview \
        db-dump-data db-prod-bootstrap \
        deploy deploy-dry migrate-prod refresh-mvs-prod logs ssh scale-up scale-down

up:
	docker compose up -d

down:
	docker compose down

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .

migrate:
	uv run alembic upgrade head

# --- Catalog pipeline (metadata: sets + cards + artwork splits) ---
# 1. Load/refresh the `sets` table from data/sets/*.yml
catalog-seed-sets:
	uv run python -m watari_catalog seed-sets

# 2. Build/refresh data/cards/{SET}/*.yml from Pokellector + TCGdex + Cardrush.
#    Usage: make catalog-bootstrap SET=SV2A
catalog-bootstrap:
	@test -n "$(SET)" || (echo "Usage: make catalog-bootstrap SET=SV2A"; exit 1)
	uv run python -m watari_catalog bootstrap-set --set $(SET)

# 3. Load/refresh artworks + cards rows from the committed YML tree.
#    Usage: make catalog-seed-cards            # all sets under data/cards/
#           make catalog-seed-cards SET=SV2A   # just one
catalog-seed-cards:
	uv run python -m watari_catalog seed-cards $(if $(SET),--set $(SET))

catalog-verify:
	uv run python -m watari_catalog verify

# --- Price scrapers ---
# Usage: make scrape-cardrush SET=SV2A
#        make scrape-cardrush ERA=SV
scrape-cardrush:
	uv run python -m watari_cardrush $(if $(SET),--set $(SET),$(if $(ERA),--era $(ERA),--all))

scrape-snkrdunk:
	uv run python -m watari_snkrdunk --era $(ERA)

# --- API (FastAPI read-side) ---
api:
	uv run watari-api --host 0.0.0.0 --port 8000

api-dev:
	uv run watari-api --host 127.0.0.1 --port 8000 --reload

# --- Web frontend (Vite + React) ---
web-install:
	cd apps/web && bun install

web-dev:
	cd apps/web && bun run dev

web-build:
	cd apps/web && bun run build

web-preview:
	cd apps/web && bun run preview

# --- Ops / deployment helpers ---
db-dump-data:
	./scripts/dump_prod_data.sh

db-prod-bootstrap:
	./scripts/prod_bootstrap.sh

# ── Production ops (Fly.io) ─────────────────────────────────
deploy:
	fly deploy --remote-only

deploy-dry:
	fly deploy --dry-run

migrate-prod:
	fly ssh console -a watari-api -C "uv run alembic upgrade head"

refresh-mvs-prod:
	fly ssh console -a watari-api -C "uv run watari-api refresh-mvs"

logs:
	fly logs -a watari-api

ssh:
	fly ssh console -a watari-api

scale-up:
	fly scale count 1 -a watari-api

scale-down:
	fly scale count 0 -a watari-api
