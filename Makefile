.PHONY: up down test lint format migrate \
        catalog-seed-sets catalog-bootstrap catalog-seed-cards catalog-verify \
        scrape-cardrush scrape-snkrdunk

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
	uv run python -m pokeprice_catalog seed-sets

# 2. Build/refresh data/cards/{SET}/*.yml from Pokellector + TCGdex + Cardrush.
#    Usage: make catalog-bootstrap SET=SV2A
catalog-bootstrap:
	@test -n "$(SET)" || (echo "Usage: make catalog-bootstrap SET=SV2A"; exit 1)
	uv run python -m pokeprice_catalog bootstrap-set --set $(SET)

# 3. Load/refresh artworks + cards rows from the committed YML tree.
#    Usage: make catalog-seed-cards            # all sets under data/cards/
#           make catalog-seed-cards SET=SV2A   # just one
catalog-seed-cards:
	uv run python -m pokeprice_catalog seed-cards $(if $(SET),--set $(SET))

catalog-verify:
	uv run python -m pokeprice_catalog verify

# --- Price scrapers ---
# Usage: make scrape-cardrush SET=SV2A
#        make scrape-cardrush ERA=SV
scrape-cardrush:
	uv run python -m pokeprice_cardrush $(if $(SET),--set $(SET),$(if $(ERA),--era $(ERA),--all))

scrape-snkrdunk:
	uv run python -m pokeprice_snkrdunk --era $(ERA)
