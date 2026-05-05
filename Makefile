.PHONY: up down test lint format migrate \
        catalog-seed-sets catalog-bootstrap catalog-seed-cards catalog-verify catalog-verify-pokellector \
        catalog-audit catalog-audit-fetch catalog-audit-diff catalog-audit-apply catalog-audit-rollout \
        sync-set-symbols \
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
	uv run python -m pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .

migrate:
	uv run python -m alembic upgrade head

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
	uv run python -m watari_catalog verify $(if $(STRICT),--strict,)

# Compare data/cards local_ids to live jp.pokellector.com set indexes (network).
catalog-verify-pokellector:
	uv run python -m watari_catalog verify-pokellector

# --- Catalog data-quality audit (TCGCollector-anchored sidecar) ---
# Phase 1: walk YMLs and write reports/catalog-audit-*.md (no data changes).
#         Usage: make catalog-audit [SET=SV4A]
catalog-audit:
	uv run python -m watari_catalog audit-current $(if $(SET),--set $(SET))

# Phase 2: scrape TCGCollector for one set (requires tcgcollector_id +
#         tcgcollector_slug in data/sets/<SET>.yml). Writes data/audit/<SET>.yml.
#         Usage: make catalog-audit-fetch SET=SV2A
catalog-audit-fetch:
	@test -n "$(SET)" || (echo "Usage: make catalog-audit-fetch SET=SV2A"; exit 1)
	uv run python -m watari_catalog audit-fetch --set $(SET)

# Phase 3: diff data/audit vs data/cards. Writes reports/audit-diff-*.md|.tsv.
#         Usage: make catalog-audit-diff [SET=SV2A]
catalog-audit-diff:
	uv run python -m watari_catalog audit-diff $(if $(SET),--set $(SET))

# Phase 5: apply audit values from a TSV. Pass MODE=auto|review.
#         Optional CONFLICTS=1 with MODE=auto applies CONFLICT rows (oracle wins).
#         Usage: make catalog-audit-apply TSV=reports/audit-diff-...tsv MODE=auto
#                make catalog-audit-apply TSV=... MODE=auto CONFLICTS=1
#                make catalog-audit-apply TSV=reports/audit-diff-...tsv MODE=review
catalog-audit-apply:
	@test -n "$(TSV)" || (echo "Usage: make catalog-audit-apply TSV=reports/...tsv MODE=auto|review"; exit 1)
	@test -n "$(MODE)" || (echo "Usage: pass MODE=auto or MODE=review"; exit 1)
	@if [ "$(MODE)" = "review" ]; then \
	  uv run python -m watari_catalog audit-apply --tsv "$(TSV)" --review; \
	elif [ "$(CONFLICTS)" = "1" ]; then \
	  uv run python -m watari_catalog audit-apply --tsv "$(TSV)" --auto --conflicts; \
	else \
	  uv run python -m watari_catalog audit-apply --tsv "$(TSV)" --auto; \
	fi

# Phase 6: per-set rollout — fetch, diff, apply AUTO_FILL, re-seed DB.
#         Usage: make catalog-audit-rollout SET=SV4A
catalog-audit-rollout:
	@test -n "$(SET)" || (echo "Usage: make catalog-audit-rollout SET=SV4A"; exit 1)
	uv run python -m watari_catalog audit-fetch --set $(SET)
	uv run python -m watari_catalog audit-diff --set $(SET)
	@TSV=$$(ls -t reports/audit-diff-$(SET)-*.tsv | head -1); \
	echo "Applying AUTO_FILL from $$TSV"; \
	uv run python -m watari_catalog audit-apply --tsv "$$TSV" --auto
	uv run python -m watari_catalog seed-cards --set $(SET)

# Rebuild apps/web SET_SYMBOL_URLS from Bulbapedia markdown export.
# Usage: make sync-set-symbols [SYMBOLS_MD=/abs/path/to/List_of_...md]
sync-set-symbols:
	uv run python scripts/update_set_symbols.py $(if $(SYMBOLS_MD),--source "$(SYMBOLS_MD)",)

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
