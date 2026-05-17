# Changelog

All notable changes to this project are documented here.

---

## [Unreleased] — Online Mode

> Maintenance-free deployment: no PostgreSQL, no Redis, no scheduled scrapers.

### Added

- **`packages/api/watari_api/catalog_mem.py`** — `MemCatalog` loads all
  `data/sets/*.yml` and `data/cards/{SET}/*.yml` files into memory at API
  startup. Indexed by `set_code` and `(set_code, local_id)` for O(1) lookups.
  Supports `get_sets`, `get_set`, `get_artworks`, `get_artwork`,
  `search_artworks`, and `get_rarities`. No database required.

- **`packages/api/watari_api/price_proxy.py`** — `PriceProxy` fetches prices
  on-demand from Cardrush and Snkrdunk at request time. Results are cached
  in-process for 30 minutes (configurable via `CACHE_TTL`). Per-key
  `asyncio.Lock` prevents thundering-herd on cold cache. Provides
  `latest_prices`, `market_price`, `spread`, `graded_prices`, and
  `graded_history` methods mirroring the old MV-backed endpoints.
  - Cardrush: searches `"{set_code} {local_id}"` keyword, respects
    `_CARDRUSH_BASE_ALIAS` for aliased SM/SW sets and `_CARDRUSH_PROMO_KEYWORD`
    for promo sets.
  - Snkrdunk: `resolve_apparel` + `fetch_sales_history`, respects
    `_SNKRDUNK_ERA_SLUG_OVERRIDE` for promo era slugs.
  - Market price logic: Snkrdunk 7-day median preferred; Cardrush condition-A
    floor as fallback (same as `mv_market_price` logic).

### Changed

- **`packages/api/watari_api/main.py`** — Lifespan now initialises
  `MemCatalog`, `PriceProxy`, and in-memory `RateLimiter` on `app.state`.
  Redis connection and SQLAlchemy session factory removed.

- **`packages/api/watari_api/auth.py`** — Simplified to always return
  anonymous/free-tier `AuthContext`. `X-API-Key` header is ignored. Removed
  `hash_api_key`, `mint_api_key`, `API_KEY_PLAINTEXT_PREFIX`,
  `LAST_USED_THROTTLE`, and all DB interaction.

- **`packages/api/watari_api/ratelimit.py`** — Redis Lua token bucket replaced
  with an in-memory `asyncio.Lock`-based implementation (`_BucketState` dict).
  Same `Bucket`, `Decision`, `parse_rate_limits`, and `rate_limit_dep`
  interface preserved. State is process-local and resets on restart.

- **`packages/api/watari_api/deps.py`** — Replaced `get_session`
  (SQLAlchemy `AsyncSession`) with `get_catalog` and `get_price_proxy`
  (both read from `request.app.state`). Kept `validate_lang`.

- **`packages/api/watari_api/routers/sets.py`** — Rewritten to use
  `CatalogDep = Annotated[MemCatalog, Depends(get_catalog)]`.
  `total_value_jpy` is always `None` (no aggregate DB query).
  `created_at`/`updated_at` on `SetOut` are populated from `MemSet.loaded_at`
  (catalog load time).

- **`packages/api/watari_api/routers/cards.py`** — Rewritten to use
  `CatalogDep`. All search/batch/by-sets results have `market_price_jpy=None`
  and `cardrush_a_floor_jpy=None`. Added `GET /cards/rarities` endpoint.

- **`packages/api/watari_api/routers/prices.py`** — Rewritten to use
  `PriceProxyDep`. `_resolve_card_id` replaces the DB-backed `_resolve_card`.
  `/history` always returns `[]`. Cache-Control for price endpoints is
  `public, max-age=1800, stale-while-revalidate=60`.

- **`packages/api/watari_api/routers/admin.py`** — Stubbed; `/admin/scrape-health`
  always returns `[]` (no `scrape_runs` table in online mode).

- **`packages/api/watari_api/cli.py`** — Simplified to `serve` subcommand only.
  Removed `create-key`, `revoke-key`, `list-keys`, and `refresh-mvs`.

- **`packages/api/pyproject.toml`** — Added `watari-catalog`, `watari-cardrush`,
  `watari-snkrdunk` as explicit workspace dependencies. Removed `redis>=5.0`.

- **`.github/workflows/scrape.yml`** — Removed all `schedule:` triggers.
  Scrapers remain available via `workflow_dispatch` for manual runs.

### Tests

- **`tests/unit/test_api.py`** — Full rewrite (36 tests). `FakeSession` +
  `get_session` injection replaced by `FakeMemCatalog` + `FakePriceProxy` +
  `get_catalog` / `get_price_proxy` overrides. Behavioral expectations updated:
  `total_value_jpy=None`, `market_price_jpy=None` in search/batch results,
  `/history` returns `[]`, price Cache-Control is `max-age=1800`.

- **`tests/unit/test_api_auth.py`** — Rewritten (4 tests). Removed DB-dependent
  hash/mint/revoked/valid-key/last-used tests. Now tests that `get_auth_context`
  always returns anonymous context, ignores `X-API-Key`, and encodes client IP.

- **`tests/unit/test_api_ratelimit.py`** — Updated (8 tests). Removed
  `_MinimalRedisStub` and Redis constructor arg. Fixed `rl_client` fixture to
  inject `get_catalog` / `_EmptyCatalog` instead of `get_session`.

- **`tests/unit/test_api_cli.py`** — Trimmed (3 tests). Removed tests for
  deleted subcommands (`create-key`, `revoke-key`, `list-keys`, `refresh-mvs`).

- **`tests/unit/test_mvs.py`** — Unchanged (5 tests). `watari_core.mvs` is
  unmodified and all tests still pass.

**Total: 399 tests passing** (down from 415; reduction is the deleted
DB/Redis/key-management tests that no longer have corresponding code).

---

## Previous releases

### 2026-05-10 — Promo + Classic sets; TCGCollector bootstrap path

- 7 new set YAMLs: CLF, CLL, CLK (Classic era), MP, SMPR, SP, SVP (promo series).
- `bootstrap_set_from_tcgcollector` for sets without a Pokellector slug.
- `Promo` rarity → `PR` in `canonicalize_tcgcollector`.
- Promo URL regex fix; image URLs extracted from TCGCollector grid tiles.
- CI jobs for Classic (daily Cardrush) and promo eras.
- 105 sets · 12 005 artworks · 12 955 cards · **415 tests**.

### 2026-05-08 — Graded price tracker (PSA/BGS/CGC)

- `graded_price_points` table (migration `008`).
- `GradeCompany` enum, `parse_grade_company_score`, `extract_cardrush_grade`.
- SNKRDUNK `parse_sales_history` returns `(ungraded, graded)` tuple.
- `GET /{lang}/cards/{set}/{id}/graded-prices` and `/graded-history` endpoints.
- `GradedPriceHistoryChart` on the card detail page (Recharts, day-range toggle).
- 402 tests.

### 2026-05-06 — Catalog v3 (YML tree); 98 sets fully bootstrapped

- One YAML per `(set, local_id)` under `data/cards/`.
- `artwork_id` / `card_id` ID scheme locked in.
- Materialized views: `mv_latest_price`, `mv_median_7d`, `mv_cross_source_spread`,
  `mv_market_price` (migrations 005–007).
- Cardrush SM/SW disambiguation (`_CARDRUSH_BASE_ALIAS`).
- Currency toggle (JPY/USD/VND) in the web UI.
