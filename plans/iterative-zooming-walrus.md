# Plan: Initialize Project — M0 (Repo Skeleton) + M1 (Core Package + Schema)

## Context

Starting from an empty directory. The user has a detailed implementation plan for "watari" — a Japanese Pokemon TCG price data service. This plan implements the first two milestones: repo skeleton with Docker Compose infrastructure (M0) and the core package with database schema + condition parsing (M1).

The user's plan document (Parts B–D) is the authoritative spec. Every table, column name, enum value, and index must match the DDL in Part C exactly.

## File Creation Order

### Step 1: Git init + .gitignore

```bash
git init
```

Create `.gitignore` — standard Python ignores, include `.env`, exclude `uv.lock` from ignoring (keep in git).

### Step 2: Root `pyproject.toml` (uv workspace)

- Workspace root with `[tool.uv.workspace] members = ["packages/*"]`
- `requires-python = ">=3.12"`
- Dev deps: pytest, pytest-asyncio, pytest-cov, ruff, mypy, pre-commit
- Tool config for ruff, mypy, pytest

### Step 3: Create directory skeleton

Matches §B.2 exactly (flat layout, no `src/` dirs):

```
packages/
├── core/watari_core/         ← config, db, models, schemas, conditions, catalog, bronze
├── scraper_cardrush/watari_cardrush/   ← stub __init__.py only
├── scraper_snkrdunk/watari_snkrdunk/   ← stub
├── dispatcher/watari_dispatcher/       ← stub
├── scheduler/watari_scheduler/         ← stub
└── api/watari_api/                     ← stub
migrations/versions/
scripts/
tests/unit/
tests/integration/
tests/fixtures/
```

### Step 4: Core package — `packages/core/pyproject.toml`

Dependencies:
- `sqlalchemy[asyncio]>=2.0`, `asyncpg`, `psycopg2-binary` (Alembic sync)
- `pydantic>=2.0`, `pydantic-settings>=2.0`
- `alembic>=1.14`
- `boto3>=1.35`
- `argon2-cffi>=23.1`

Build backend: hatchling, flat layout `packages = ["watari_core"]`

### Step 5: Core modules (in dependency order)

1. **`watari_core/__init__.py`**
2. **`watari_core/config.py`** — pydantic-settings `Settings` class reading `.env`
3. **`watari_core/db.py`** — SQLAlchemy `Base`, async engine factory, session generator
4. **`watari_core/conditions.py`** — Exact code from §D:
   - `Condition` enum: `RAW_A, RAW_A_MINUS, RAW_B, RAW_C` (only 4 values for v1)
   - `parse_cardrush_condition(name) -> tuple[Condition | None, bool]` — returns `(condition, is_graded)`
   - `parse_snkrdunk_condition(api_condition) -> Condition | None`
   - Graded regex `【(PSA|BGS|CGC|SGC)\d+】` → `is_graded=True`, skip for v1
   - SNKRDUNK: S→RAW_A, A→RAW_A, B→RAW_B, C→RAW_C
5. **`watari_core/catalog.py`** — `make_card_id(era, local_id) -> "jp-{era}-{local_id}"`, parser
6. **`watari_core/models.py`** — ORM models matching §C DDL exactly:
   - `cards` — `card_id TEXT PK`, `era`, `local_id`, `total`, `name_ja`, `name_en`, `rarity`, `set_name_ja`, `set_name_en`, `set_release_date`, `image_url`, `tier`, `is_tracked`, timestamps
   - `scrape_runs` — `BIGSERIAL PK`, `source TEXT`, status/counts/metadata JSONB
   - `card_scrape_state` — composite PK `(card_id, source)`, failure tracking
   - `price_points` — `BIGSERIAL PK`, enums `condition_enum(RAW_A/RAW_A_MINUS/RAW_B/RAW_C)`, `source_enum(cardrush/snkrdunk)`, `source_type_enum(listing/sold)`, idempotency unique index
   - `api_keys` — `BIGSERIAL PK`, argon2 hash, tier free/pro
7. **`watari_core/schemas.py`** — Pydantic DTOs for cards, price points
8. **`watari_core/bronze.py`** — boto3 S3 client for MinIO, `ensure_bucket()`, `write_bronze()`

### Step 6: Stub packages (5 packages)

Each gets a `pyproject.toml` + `__init__.py`. Depend on `watari-core`. No real code yet.

### Step 7: `docker-compose.yml`

Exact spec from §B.1:
- `postgres:16` — watari/watari/watari, port 5432, health check
- `minio/minio` — watari/watari123, ports 9000+9001, health check
- `redis:7-alpine` — port 6379, health check
- `pgadmin4` — debug profile only

### Step 8: `.env.example`

From §B.4 — DATABASE_URL, REDIS_URL, S3_ENDPOINT_URL, scraper jitter, API CORS, etc.

### Step 9: `Makefile`

Targets: `up`, `down`, `test`, `seed`, `lint`, `format`, `migrate`

### Step 10: `.pre-commit-config.yaml`

ruff (lint + format)

### Step 11: `uv sync`

Installs all workspace members, creates `uv.lock`.

### Step 12: Alembic setup

- `uv run alembic init -t async migrations`
- Edit `alembic.ini` — set sqlalchemy.url
- Edit `migrations/env.py` — import Base + all models, async engine pattern
- `uv run alembic revision --autogenerate -m "initial_schema"`
- Review generated migration — verify all tables, enums, indexes match §C DDL
- Manually add materialized views to a separate migration (autogenerate won't detect them)

### Step 13: Tests

- `tests/unit/test_smoke.py` — basic pass
- `tests/unit/test_conditions.py` — ≥15 cases per §D edge cases:
  - Cardrush: no bracket→RAW_A, 〔状態A-〕→RAW_A_MINUS, 〔状態B+〕→RAW_B, 【PSA10】→graded, graded+bracket→graded wins, 【AR】rarity→not graded, unknown bracket→None
  - SNKRDUNK: S→RAW_A, A→RAW_A, B→RAW_B, C→RAW_C, lowercase, whitespace, unknown→None
- `tests/unit/test_catalog.py` — card_id generation/parsing

### Step 14: Verify + commit

```bash
docker compose up -d
uv run alembic upgrade head
uv run pytest
# Verify AC:
# psql ... -c '\d price_points'
# curl http://localhost:9000/minio/health/live
```

## Critical Design Constraints (from user's plan)

1. **Condition enum has exactly 4 values for v1:** `RAW_A, RAW_A_MINUS, RAW_B, RAW_C`. Graded cards are detected and skipped, not stored.
2. **card_id format:** `jp-{era}-{local_id}` (e.g., `jp-sv2a-183`). This is a TEXT primary key.
3. **price_points is append-only.** Idempotency via unique index on `(card_id, source, source_type, condition, price_jpy, observed_at, COALESCE(external_url, ''))`.
4. **BIGSERIAL primary keys** (not UUIDs) for price_points, scrape_runs, api_keys.
5. **source_type_enum:** `listing | sold` (not retail/marketplace).
6. **Bronze before silver.** Raw HTML/JSON stored in MinIO before parsing.
7. **Flat package layout** matching §B.2 — `packages/core/watari_core/`, not `packages/core/src/watari_core/`.

## Verification

After implementation:
- `docker compose up -d && uv sync && uv run pytest` → all green
- `psql postgresql://watari:watari@localhost:5432/watari -c '\l'` → connects
- `curl http://localhost:9000/minio/health/live` → 200
- `uv run alembic upgrade head` → all tables created
- `uv run pytest tests/unit/test_conditions.py` → ≥15 tests pass
- `psql ... -c '\d price_points'` → matches §C DDL exactly
