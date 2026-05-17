# CLAUDE.md — Project State & Roadmap

> **Purpose:** this file is the handoff note for the next Claude session.
> It captures "what the codebase is", "what just landed", "what's next",
> and the handful of invariants that are easy to break.
> Update it whenever the architecture changes — especially after a
> destructive migration, a new source, or a schema split.
>
> Last updated: 2026-05-17 (**Online mode** — API now fetches prices on-demand from Cardrush/Snkrdunk; PostgreSQL and Redis removed from the API layer; in-memory catalog (`MemCatalog`) + in-memory rate limiter; CI scrapers disabled (schedule removed, `workflow_dispatch` only); 399 tests passing).

---

## 1. Project TL;DR

Universal Pokémon TCG price API for the **Japanese** market.

Three concerns, cleanly separated:

| Layer       | Responsibility                                                                     | Code                                        |
| ----------- | ---------------------------------------------------------------------------------- | ------------------------------------------- |
| **Catalog** | What cards exist (sets, artworks, print variants). Source of truth: YML.           | `packages/catalog/`, `data/`                |
| **Prices**  | Fetched **on-demand** from Cardrush (HTML) + Snkrdunk (JSON) at request time.     | `packages/api/watari_api/price_proxy.py`    |
| **API**     | Read-side (FastAPI). In-memory catalog; no DB required.                            | `packages/api/`                             |

**Online mode (current):** The API no longer requires PostgreSQL or Redis.
- `MemCatalog` loads all YAML files into memory at startup (sets + cards).
- `PriceProxy` fetches prices live from Cardrush/Snkrdunk, cached 30 min in-process.
- Rate limiting uses an in-memory token bucket (no Redis).
- All requests are anonymous/free-tier (no API-key DB).
- CI scraper schedule is disabled; scrapers still work via `workflow_dispatch`.

Stack: Python 3.13, `uv` workspaces, `curl_cffi` for Cloudflare-fronted sites,
`httpx` for everything else.
Frontend: Vite + React + TypeScript, `bun` package manager (`apps/web/`).
React Query (`@tanstack/react-query`) for all data fetching and exchange-rate caching.

The PostgreSQL schema + Alembic migrations still exist in `packages/core/` and
`migrations/` for historical reference and potential future re-enablement, but
they are not exercised by the API in online mode.

---

## 2. Repo layout

```
apps/
  web/                 ← Vite + React frontend (bun; VITE_API_BASE_URL → FastAPI)
    src/
      contexts/        ← CurrencyContext.tsx (global JPY/USD/VND toggle, Frankfurter rates)
      components/
        layout/        ← Header, ThemeToggle, CurrencyToggle
        cards/         ← CardThumbnail, SearchCardThumbnail, CardGrid, CardSkeleton, …
        prices/        ← PriceTable, SpreadTable, PriceHistoryChart, GradedPriceHistoryChart
        sets/          ← SetCard, SetsFilterBar, …
        ui/            ← Badge, Skeleton, Pagination, ErrorMessage, …
      pages/           ← SetsPage, CardsPage, CardsSearchPage, CardDetailPage, AdminPage
      api/             ← useCards, useCardSearch, useMarketPrice, useLatestPrices, …
      lib/             ← formatters.ts (formatJPY, formatPrice), constants.ts, sortSearchCards.ts
      types/           ← api.ts (ArtworkDetail, ArtworkSearchResult, SetOut, …)
packages/
  core/                ← SQLAlchemy models, Pydantic DTOs, catalog.py helpers, bronze writer
  catalog/             ← YML data tree + bootstrap/seed pipeline + CLI
    data/
      sets/*.yml       ← 98 set files (source of truth for set metadata, 4 eras)
      cards/{SET}/*.yml← one file per (set, local_id); 10 787 files total
    watari_catalog/    ← Python package (bootstrap.py, seed_cards.py, clients, verify_pokellector.py, …)
  scraper_cardrush/    ← curl_cffi-based scraper, rarity-bucket crawling
  scraper_snkrdunk/    ← cookie-auth snkrdunk sold-price scraper
  dispatcher/          ← job dispatch (placeholder)
  scheduler/           ← cron/apscheduler shell (placeholder; live schedule is in CI)
  api/                 ← FastAPI read layer
migrations/            ← Alembic (current head: 008_graded_price_points)
scripts/               ← gen_sm/sw_set_metadata.py, update_set_symbols.py, dump/bootstrap scripts
plans/                 ← design docs, one per major change
tests/unit/            ← 362 tests, all passing
```

Config knobs: `.env` (DB URL, MinIO creds, SNKRDUNK cookies). `docker-compose.yml`
brings up Postgres + MinIO.

---

## 3. Current architecture — Catalog v3 (shipped)

### 3.1 Schema (post-migration `008_graded_price_points`)

```
sets        ── 1 row per set (set_code PK). source_refs.pokellector_slug is required for bootstrap.
artworks    ── 1 row per (set_code, local_id). Owns name_ja/en, image_url, rarity_code,
               illustrator, category. artwork_id = "jp-{set_code_lower}-{local_id_padded}".
cards       ── 1 row per print (set_code, local_id, variant). artwork_id FK → artworks.
               card_id = "{artwork_id}-{variant}". price_points.card_id FKs here.
price_points, card_scrape_state, scrape_runs ← unchanged in shape.
mv_latest_price, mv_median_7d, mv_cross_source_spread, mv_market_price
             ← all four have a UNIQUE index so REFRESH MATERIALIZED VIEW
             CONCURRENTLY works (005/006/007).
graded_price_points ← separate table for PSA/BGS/CGC sold comps.
             Unique index on (card_id, source, grade_company, grade_score,
             price_jpy, observed_at, COALESCE(external_url,'')) (008).
             mv_market_price: one row per card_id, picks SNKRDUNK 7-day median
             if available, else Cardrush condition-A floor.
```

**Important:** `artworks.name_ja` is **nullable**. New sets (e.g. M2A Commons)
often have no JA name from Pokellector/TCGdex/Cardrush at bootstrap time; we
persist NULL so `verify` can flag them.

### 3.2 Data flow

```
Pokellector (primary) ─┐
TCGdex (fallback)      ├── bootstrap-set → data/cards/{SET}/{NNN}.yml (git-versioned)
Cardrush (variants)    ─┘                        │
                                                 ▼
                                           seed-cards → artworks + cards tables
                                                 │
                     cardrush-scrape, snkrdunk-scrape ← uses `cards` for target list
                                                 │
                                                 ▼
                                           price_points + bronze (MinIO)
                                                 │
                                                 ▼
                        refresh_price_mvs_if_needed  (post-commit hook, see §3.6)
                                                 │
                                                 ▼
                 mv_latest_price → mv_median_7d → mv_cross_source_spread
                                  (CONCURRENTLY, one COMMIT per view)
```

**Source precedence (baked into `bootstrap.py::_merge_one`):**

| Field         | Winner                                                |
| ------------- | ----------------------------------------------------- |
| `image`       | Pokellector (always)                                  |
| `name_en`     | Pokellector                                           |
| `name_ja`     | TCGdex → Cardrush (variant suffix stripped)           |
| `rarity_code` | Pokellector (via `canonicalize_pokellector`) → TCGdex |
| `illustrator` | TCGdex only                                           |
| `prints`      | `{normal}` ∪ Cardrush-observed variants               |
| `category`    | TCGdex.category → keyword heuristic on name           |

### 3.3 YML file contract (`data/cards/{SET}/{NNN}.yml`)

```yaml
# SV2A #089. Generated by `python -m watari_catalog bootstrap-set`.
# To freeze a manually-edited value, add `# manual: true` on line 1.
set_code: SV2A
local_id: "089"
name_ja: ベトベトン
name_en: Muk
rarity_code: U
category: card # card | trainer | energy
image: https://den-cards.pokellector.com/371/Muk.SV2A.89.48301.png
illustrator:
prints:
  - normal
  - master_ball_mirror
  - poke_ball_mirror
sources:
  pokellector:
    {
      id: "48301",
      series_id: "371",
      slug: "Muk-Card-89",
      rarity_raw: "Uncommon",
    }
  tcgdex: { id: "89", rarity_raw: null }
  cardrush:
    {
      name_ja: "ベトベトン",
      variants_seen: [normal, master_ball_mirror, poke_ball_mirror],
    }
```

**Rules:**

- YMLs are edited by hand when the pipeline gets something wrong.
  Add `# manual: true` as **line 1** to freeze them.
- `emit_yml.py` uses `ruamel.yaml` round-trip so your comments/order survive.
- Re-running `bootstrap-set` on an unmarked YML will overwrite if content
  changed (and will quietly skip if unchanged).

### 3.4 IDs

```
artwork_id  = "jp-{set_code_lower}-{local_id_padded_to_3}"     e.g. "jp-sv2a-089"
card_id     = "{artwork_id}-{variant}"                          e.g. "jp-sv2a-089-master_ball_mirror"
```

Helpers live in `packages/core/watari_core/catalog.py`
(`make_artwork_id`, `make_card_id`, `parse_card_id`, `artwork_id_for_card`,
`parse_artwork_id`, `pad_local_id`).

**Watch out:** `parse_artwork_id` / `parse_card_id` split on `"-"` and assume
exactly 3 / 4 segments. If a set_code ever contains a hyphen (e.g. `"sv-p"`)
they will misparse. None of the current 98 set codes contain hyphens.

### 3.5 API layer (`packages/api/`, read-only, online mode)

Built on FastAPI. **No PostgreSQL or Redis required.** Catalog served from
memory; prices fetched live and cached in-process.

**Key new files:**

| File | Role |
|------|------|
| `watari_api/catalog_mem.py` | `MemCatalog` — loads all YAML at startup; indexed by `(set_code, local_id)` |
| `watari_api/price_proxy.py` | `PriceProxy` — on-demand Cardrush + Snkrdunk fetch; 30-min TTL per-key cache |

Routers (all under `packages/api/watari_api/routers/`):

| Route | Returns | Source |
| ----- | ------- | ------ |
| `GET /healthz` | `{"status": "ok"}` | — |
| `GET /{lang}/sets` (`?era=sv`) | `list[SetOut]` | `MemCatalog` |
| `GET /{lang}/sets/{set_code}` | `SetOut` / 404 | `MemCatalog` |
| `GET /{lang}/sets/{set_code}/cards` (`?variant=&rarity=&tracked_only=`) | `list[ArtworkDetail]` | `MemCatalog` |
| `GET /{lang}/cards/{set_code}/{local_id}` | `ArtworkDetail` / 404 | `MemCatalog` |
| `GET /{lang}/cards/search` | `list[ArtworkSearchResult]` | `MemCatalog` (`market_price_jpy=null`) |
| `GET /{lang}/cards/batch` / `POST` | `list[CardBatchItem]` | `MemCatalog` |
| `GET /{lang}/cards/by-sets` / `POST` | `list[ArtworkSearchResult]` | `MemCatalog` |
| `GET /{lang}/cards/{set_code}/{local_id}/prices` (`?variant=normal`) | `list[LatestPrice]` | `PriceProxy` (live; 30-min cache) |
| `GET /{lang}/cards/{set_code}/{local_id}/history` | `[]` (always empty) | — (no DB) |
| `GET /{lang}/cards/{set_code}/{local_id}/spread` (`?variant=normal`) | `list[SpreadRow]` | `PriceProxy` |
| `GET /{lang}/cards/{set_code}/{local_id}/market-price` (`?variant=normal`) | `MarketPriceOut` / 404 | `PriceProxy` |
| `GET /{lang}/cards/{set_code}/{local_id}/graded-prices` (`?variant=normal`) | `list[LatestGradedPrice]` | `PriceProxy` |
| `GET /{lang}/cards/{set_code}/{local_id}/graded-history` (`?days=365&company=PSA`) | `list[GradedPricePointOut]` | `PriceProxy` |
| `GET /admin/scrape-health` | `[]` (always empty) | — (no DB) |

**Online mode trade-offs:**

- `/prices`, `/spread`, `/market-price`, `/graded-*` — first call per card takes
  2–5 s (live HTML scrape + JSON API). Cached for 30 min thereafter.
- `/history` — always returns `[]` (no price_points table).
- `market_price_jpy` — always `null` in `/search`, `/batch`, `/by-sets` results.
- `total_value_jpy` — always `null` on set objects.
- `/admin/scrape-health` — always returns `[]`.

**Auth + rate limiting** (`auth.py`, `ratelimit.py`):

- All requests are anonymous/free-tier. `X-API-Key` header is ignored.
- Rate limiter: in-memory token bucket (per-process, resets on restart).
  Config: `settings.api_rate_limits = "free:60:1.0,..."` (same format as before).
  Responses carry `X-RateLimit-{Tier,Limit,Remaining}`; denied → **429** + `Retry-After`.

**Run:** `make api` (prod) or `make api-dev` (reload). Entry point is
`watari-api` console script → `watari_api.cli:main`.

**CLI subcommands (online mode):**

- `watari-api serve [--host --port --reload]` — run uvicorn (default).
  Key-management (`create-key`, `revoke-key`, `list-keys`) and `refresh-mvs`
  commands have been removed.

**Tests:** `tests/unit/test_api.py` (36) uses `dependency_overrides` to inject
`FakeMemCatalog` + `FakePriceProxy` + anonymous rate-limit no-op. Auth / rate-limit /
CLI tests have their own files (`test_api_auth.py` 4, `test_api_ratelimit.py` 8,
`test_api_cli.py` 3, `test_mvs.py` 5 — MVs still tested since `watari_core.mvs` is
unchanged). None of the API tests require Postgres or Redis.

### 3.6 Post-scrape MV refresh hook (`packages/core/watari_core/mvs.py`)

Price/spread endpoints read MVs, not `price_points` — MVs must be refreshed after each scrape.

- `refresh_price_mvs(session, *, concurrently=True)` — refreshes all four views in dependency
  order (`mv_latest_price` → `mv_median_7d` → `mv_cross_source_spread` → `mv_market_price`),
  one COMMIT per view so locks release between them.
- `refresh_price_mvs_if_needed(*, rows_written, dry_run=False)` — guard called from scrapers.
  Opens its own session, skips on `dry_run=True` or `rows_written==0`, **swallows + logs** any
  exception. A failed refresh must never abort a successful scrape.

**Call sites:** `scrape_set` (Cardrush), `scrape_era` (SNKRDUNK) — both after `finish_scrape_run`
commits; and `watari-api refresh-mvs` for manual use. Each MV needs a UNIQUE index for
`CONCURRENTLY` (005: first two, 006: spread, 007: market_price).

### 3.7 Frontend architecture (`apps/web/`)

Stack: Vite + React 18 + TypeScript + Tailwind CSS + React Query + Recharts. `bun` as package manager.

**Pages & routing** (React Router, file `src/App.tsx`):

| Route | Page | Description |
|-------|------|-------------|
| `/` | `SetsPage` | Grid of all 98 sets with era/sort/search filters, pagination |
| `/sets/:setCode` | `CardsPage` | Cards for one set (uses `useCardSearch` for embedded prices) |
| `/sets/:setCode/:localId` | `CardDetailPage` | Card detail: image, variants, PriceTable, SpreadTable, PriceHistoryChart, GradedPriceHistoryChart |
| `/cards` | `CardsSearchPage` | Cross-set card search with name/set/rarity/illustrator/sort filters |
| `/admin` | `AdminPage` | Scrape health dashboard (GET /admin/scrape-health) |

**Key data fetching hooks** (`src/api/`):

| Hook | Endpoint | Notes |
|------|----------|-------|
| `useAllSets` | `GET /jp/sets` | Sets list; sort/era params |
| `useSet` | `GET /jp/sets/{code}` | Single set |
| `useCards` | `GET /jp/sets/{code}/cards` | `ArtworkDetail[]`, no prices |
| `useCardSearch` | `GET /jp/cards/search` | `ArtworkSearchResult[]` — **includes embedded `market_price_jpy`** |
| `useCard` | `GET /jp/cards/{set}/{id}` | Single `ArtworkDetail` |
| `useMarketPrice` | `GET /jp/cards/{set}/{id}/market-price` | Per-variant market price; accepts `enabled` param |
| `useLatestPrices` | `GET /jp/cards/{set}/{id}/prices` | All condition rows from `mv_latest_price` |
| `useSpread` | `GET /jp/cards/{set}/{id}/spread` | Cross-source spread from `mv_cross_source_spread` |
| `usePriceHistory` | `GET /jp/cards/{set}/{id}/history` | Raw `price_points` for chart |
| `useGradedPriceHistory` | `GET /jp/cards/{set}/{id}/graded-history` | Raw `graded_price_points`; default 365 days, limit 2000 |

**Currency system** (`src/contexts/CurrencyContext.tsx`):

- `CurrencyProvider` wraps the whole app (inside `QueryClientProvider`).
- Reads initial currency from `localStorage.currency` (JPY default).
- `useExchangeRates()` — React Query, fetches `https://api.frankfurter.app/latest?from=JPY&to=USD,VND`, `staleTime: 1h`. Falls back to `{ USD: 0.0065, VND: 163 }` on error — never throws to the UI.
- `useCurrency()` — returns `{ currency, setCurrency, rates, formatPrice }`. `formatPrice(jpy)` is the single call site for all price display.
- `formatPrice(jpy, currency, rates)` lives in `src/lib/formatters.ts` (pure function). `formatJPY` is kept as internal helper.
- `CurrencyToggle` (3-button pill ¥·$·₫) lives in `Header` between nav and ThemeToggle.

**CardThumbnail performance pattern:**

`CardThumbnail` accepts `ArtworkDetail` but `CardsPage` passes `ArtworkSearchResult` objects (which extend `ArtworkDetail` with `market_price_jpy` already included). A runtime type guard `isSearchResult` checks for the extra field:
- If present → use embedded price directly, `useMarketPrice` called with `enabled: false` (zero API requests)
- If absent → fire `useMarketPrice`, show animated pulse skeleton while pending

This eliminates 60+ individual market-price requests per set-gallery page load.

**Price display rules (current):**
- Card gallery thumbnails: price only (no "sold"/"listed" source label)
- `PriceTable` (detail page): Condition + Price only (no "Updated" date column)
- `SpreadTable`: CR Floor, SD Median 7d, Spread, Spread % — all currency-converted
- `PriceHistoryChart`: Y-axis and tooltip both call `formatPrice`
- `GradedPriceHistoryChart`: multi-line Recharts chart; one line per grade (PSA10/9/8, BGS10/9.5); SNKRDUNK sold comps preferred over Cardrush per day; day-range toggle (90/180/365)
- `SetCard` (sets page): `total_value_jpy` currency-converted

---

## 4. What works right now

### 4.1 End-to-end smoke (last run 2026-05-06, SV + ME + SM + SWSH)

| Step                                               | Result                                                                                         |
| -------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `alembic upgrade head`                             | clean (head = `008_graded_price_points`)                                                       |
| `make catalog-seed-sets`                           | 105 sets upserted (25 SV + 6 ME + 30 SWSH/S + 37 SM + 3 CL + 4 promo)                        |
| `make catalog-bootstrap SET=<code>` × 105          | all 105 sets bootstrapped; 12 005 artworks on disk; **0 null rarity_codes** (promo sets exempt) |
| `make catalog-seed-cards`                          | artworks + prints seeded across all 105 sets                                                   |
| `make catalog-verify`                              | 0 orphans · 0 artworks missing img · 471 missing name_ja (M2A/S4A/SM commons — expected)       |
| `make scrape-cardrush ERA=sv` + `ERA=me`           | ~12.7k Cardrush rows across SV+ME sets. SM/SW: scheduled weekly via CI.                       |
| `make scrape-snkrdunk ERA=<code>` × SV+ME          | ~104k SNKRDUNK rows. **SV1 still 0 rows** (upstream uses `sv1v` namespace). SM/SW: scheduled weekly via CI. |
| `watari-api refresh-mvs` (CONCURRENTLY)            | mv_latest_price, mv_median_7d, mv_cross_source_spread, mv_market_price — refreshed             |
| `uv run pytest`                                    | **399 passed** (online mode; DB/Redis API tests replaced with in-memory fakes)                 |
| `make web-dev`                                     | Currency toggle ¥/$/₫ in header; all price surfaces convert correctly; GradedPriceHistoryChart live on CardDetailPage |

### 4.2 Data that's already committed

- `data/sets/*.yml` — **105 sets** across 5 eras (98 original + 7 new: CLF/CLL/CLK `cl` era; MP/SMPR/SP/SVP promo series).
  Historical renames: **M1 → M1L** (official JP abbreviation), **M2** name corrected
  to `インフェルノX/Inferno X`, **SV7A** corrected to `楽園ドラゴーナ/Paradise Dragona`.
  **New sets require bootstrap** — pokellector_slug placeholders need verification before `make catalog-bootstrap`.
- `data/cards/{SET}/*.yml` — **10 787 files** covering all 98 original sets (CLF/CLL/CLK/MP/SMPR/SP/SVP pending bootstrap).
  Largest sets: SV4A (360), S4A (330), S8B (285), S12A (261), SM8B/M2A (250), SV8A (237),
  SM12A (226), SV2A (210), SV11W/SV11B (174 each).

### 4.3 Price data in the DB (snapshot: SV + ME fully scraped; SM/SW pending first CI run)

| Aggregate                | Value                                                       |
| ------------------------ | ----------------------------------------------------------- |
| `price_points` total     | ~117k rows (SV+ME only; SM/SW legacy scrapers not yet run) |
| Cardrush rows            | ~12 700 (all SV+ME sets)                                    |
| SNKRDUNK rows            | ~104 400 (27 SV+ME sets; SV1 empty — upstream uses `sv1v`) |
| SM/SW price data         | Pending — CI weekly legacy jobs will populate on first run  |

Per-set highlights (SV+ME): SV2A 2606 CR + 13529 SD; M2A 528 + 18198;
SV8A 381 + 15051; M1L 211 + 5839; M2 401 + 6465; SV4A 250 + 5109.

SM/SW sets are cataloged (YMLs + DB rows) but have no price data yet —
`/prices` and `/spread` will return empty arrays until the weekly CI scrape runs.
SV1 remains Cardrush-only (SNKRDUNK lists it under `sv1v`).

---

## 5. Pending / roadmap (in priority order)

### 5.1 Immediate follow-ups (next session can pick up directly)

0. **Bootstrap the 7 new sets (CLF/CLL/CLK/MP/SMPR/SP/SVP).**

- Verify/correct `pokellector_slug` values in `data/sets/{CODE}.yml` for all 7 sets.
  Current slugs are best-effort guesses — confirm by visiting Pokellector JP page for each set.
- Run `make catalog-bootstrap SET=CLF` (and CLL/CLK/MP/SMPR/SP/SVP) once slugs are correct.
- Run `make catalog-seed-sets && make catalog-seed-cards` to load into DB.
- For SNKRDUNK promo era slugs (SMPR→`sm-p`, SP→`s-p`, MP→`m-p`, SVP→`sv-p`) — probe manually
  before first CI run by running the probe script from plan Part E.
- Run `make catalog-audit-rollout SET=CLF` (+ others) after bootstrap.

1. **Investigate SNKRDUNK coverage gap for SV1.**

- SV1 (Scarlet ex) returned 108/108 `not_found`. Manual probe of
  `pkmn-tcg-sv1-001` is empty, but `pkmn-tcg-sv1v-001` works. SNKRDUNK
  appears to list all Scarlet+Violet base-set cards under `SV1V` only;
  SV1's cards might be addressable via a different product-number prefix
  (or might simply be unlisted). Low priority — Cardrush still gives
  ~700 rows for SV1.

2. **Backfill missing `name_ja`.**

- 471 artworks still lack a Japanese name. Biggest gaps: M2A (118),
  S4A (66), SM1M (30), SM1S (28), SV8A (17), SV4A (17), S12A (16),
  SM7B (14), SM3N/SM3H (13 each).
- Pokellector backfill already recovered 2009 cards (commit `1ea7977`).
  Remaining are mostly V/VMAX/GX/Trainer full-arts where Pokellector
  has English-only in the JPN field.
- Option A (preferred): scrape the official Pokemon card DB or Bulbapedia.
- Option B: wait for Cardrush to list them, re-bootstrap.
- Option C: hand-fill with `# manual: true`.

3. **Tracked-listings coverage is uneven between Cardrush and SNKRDUNK.**

- Cardrush: only actively-listed prints have a `price_points` row.
- SNKRDUNK: only cards that have actually sold appear (~20–90 per set). That's expected — SNKRDUNK is sold-comps only.
- Don't lower Cardrush's set-disambiguation filter (`listings_dropped_wrong_set`); it's working correctly.

### 5.2 Medium-term

- **First SM/SW price scrape.** The weekly CI jobs (Sunday 06:00 JST) will
  run automatically. After the first pass, check coverage with
  `make catalog-verify` and confirm SNKRDUNK product namespaces are correct
  for each legacy era (apply the M1L lesson: probe manually on `not_found=N`).
  Cardrush SM/SW disambiguation is now live (set alias + name_ja matching).
- **API polish.** Add E-Tag / `Cache-Control` headers on `/cards/{card_id}/prices`
  and `/spread`. Add OpenAPI examples. `/cards/search` already exists (powers
  `CardsSearchPage` + `CardsPage`).
- **Live rate-limit integration test.** The unit suite stubs Redis via a
  fake limiter. We don't yet have a smoke test that drives the real Lua
  token-bucket against the `docker-compose` Redis. Worth adding once CI
  has service containers.
- **Frontend: card detail market price banner.** The detail page shows
  `PriceTable` (all conditions per source) but no single prominent "market
  price" figure. Consider adding a hero price using `useMarketPrice` at the
  top of the detail panel, currency-converted.
- **Frontend: price age indicator.** Removed the "Updated" column from
  `PriceTable` for cleanliness, but stale data (>14 days old) is now
  silently shown without any warning. Consider a subtle badge on the section
  header when all rows are stale rather than per-row opacity.

### 5.3 Nice-to-haves

- `plans/iterative-zooming-walrus.md` → TCGdex-style localization rebuild (English names, type, HP, etc.).
- Variant discovery for brand-new sets (right now Cardrush Commons rarely list anything).
- A `catalog lint` command that checks every YML for required fields + image URL reachability.
- Snapshot tests for YMLs (guard against accidental regressions from bootstrap tweaks).

---

## 6. Invariants & gotchas (don't break these)

1. `**card_id` shape is load-bearing.\*\* `price_points.card_id` + MVs depend on
   it. Always build via `make_card_id(...)`, never concatenate strings.
2. `**artworks.name_ja` is nullable.\*\* Don't re-add NOT NULL or the coerce-to-name_en
   fallback in `seed_cards._artwork_row` — it hides data quality issues.
3. `**# manual: true` on line 1 of a card YML is a git-versioned override.\*\*
   `emit_yml.write_card_yaml` respects it. Don't work around it.
4. **Bootstrap is destructive to YMLs without `# manual: true`.** If a source
   flips a field, the YML is overwritten on the next run. That's by design.
5. `**fetch_tracked_cards` now joins `Artwork ↔ Card`.\*\* Any new scraper that
   needs rarity/name_ja must go through this helper (or duplicate the join).
6. **Session hygiene.** Scrapers catch per-card errors and `await session.rollback()`
   to avoid poisoning the async transaction. Keep this pattern.
7. **Bronze mirroring is required.** Both scrapers and Pokellector write raw
   payloads to MinIO (`bronze/{source}/{set_code}/...`). Don't skip it for
   "just one" source — we rely on bronze for re-parses and audits.
   Payloads ≥1 KB are **gzip-compressed** (level 6) before upload; `ContentType`
   and `ContentEncoding: gzip` are set automatically via `_compress_opts` in
   `bronze.py`. Run `make bronze-setup-lifecycle` once per bucket to install the
   90-day expiry rule.
8. `**curl_cffi` is mandatory for Cardrush.\*\* Don't "simplify" to `httpx`:
   Cardrush is behind Cloudflare TLS fingerprint checks. Playwright is a
   last resort (slow + heavy).
9. `**ruamel.yaml` is used for `data/cards/`, `PyYAML` for `data/sets/`.\*\*
   Sets YMLs are simple and diff-clean with PyYAML; card YMLs need round-trip
   preservation. Don't collapse them.
10. **API `/prices` + `/spread` read from MVs.** If MVs get stale (because
    nothing has refreshed them post-scrape), clients see old numbers with no
    error. The refresh hook (§3.6) fires on scrape completion; don't "fix"
    the latency issue by routing the endpoints back to `price_points`
    directly — that's what the MVs are for. Fix the refresh instead.
11. **FastAPI deps use `Annotated[AsyncSession, Depends(get_session)]`**
    aliased as `SessionDep` at the top of each router file. Don't regress
    to `Depends(get_session)` in defaults — ruff B008 will reject it.
12. **Rate-limit + locale validation live on the top-level `/{lang}` router
    dependency chain.** Don't duplicate `Depends(rate_limit_dep)` on
    individual sub-routers; we rely on one shared execution per request
    to stamp `X-RateLimit-`\* headers uniformly.
13. **API-key plaintext is never stored.** Only `sha256(plaintext)` goes
    into `api_keys.key_hash`. `mint_api_key()` returns the plaintext; the
    CLI prints it exactly once at issuance. Never log the plaintext and
    never read it back from the DB (it isn't there).
14. **MV refresh is a scraper responsibility, not the API's.** Scrapers
    call `refresh_price_mvs_if_needed` after `finish_scrape_run` commits
    (§3.6). The helper swallows errors on purpose — **don't** re-raise
    them; a flaky MV refresh must never fail-mask an otherwise successful
    scrape. If `CONCURRENTLY` is ever rejected (e.g. you added a 5th MV
    without a unique index), fix the index or pass `concurrently=False`
    manually via `watari-api refresh-mvs --no-concurrently`. Don't
    stop using the hook.
15. **Every price MV must have a UNIQUE index.** Required for
    `REFRESH MATERIALIZED VIEW CONCURRENTLY`. Add the index in the same
    Alembic migration that creates the MV. 005 covers
    `mv_latest_price` + `mv_median_7d`; 006 covers `mv_cross_source_spread`;
    007 covers `mv_market_price`.
16. **Use the official JP set abbreviation** (card-printed / SNKRDUNK product number),
    not a guess. ME era tripped this: Mega Brave is **M1L**, Mega Symphonia is **M1S**.
    Wrong `set_code` → Cardrush works (lenient) but SNKRDUNK returns 0 rows (`pkmn-tcg-M1L-NNN`).
    If a new set's SNKRDUNK run yields `succeeded=0 not_found=N`, **probe the product-number
    namespace manually** before assuming SNKRDUNK hasn't indexed it. Rename is destructive.
17. **Every API lookup path is locale-prefixed (`/{lang}/...`).**
    `sets.language` is the source of truth for locale routing. Keep
    `/healthz` and `/admin/*` outside locale routing, and keep unsupported
    locales as **404** (not 400) so unknown locale paths behave like
    missing routes.
18. **Cardrush SM/SW disambiguation uses `_CARDRUSH_BASE_ALIAS` +
    `name_ja` matching.** Many SM/SW sets share a Cardrush search
    namespace (e.g. S1W and S1H both return results for "S1"). The
    alias map in `run.py` maps 22 aliased set codes to their base code
    for the search keyword, then `_name_matches` cross-references
    `artworks.name_ja` to filter results to the correct set. Don't
    remove the name index or the alias map — without them, aliased sets
    get 0 valid listings.
19. **SV1S/SV1V/SV2D/SV2P rarity tiers are patched via audit pipeline.** Pokellector
    labels all high-rarity cards in these 4 sets as "Secret Rare". Phase 7 of the audit
    pipeline auto-corrects this: when Pokellector raw is `"Secret Rare"` / `"Super Secret Rare"`
    and `data/audit/<SET>.yml` has a more specific TCGCollector `rarity_canon`, the audit
    value wins (`_audit_overrides_pokellector` in `bootstrap.py`). If re-bootstrapping,
    verify no regression back to UR.
20. **TCGCollector audit data lives in `data/audit/<SET>.yml`** — never edit by hand.
    Re-run `make catalog-audit-fetch SET=<code>` to refresh. Phase-4 fallbacks
    (`pokellector_jpn`, `bulbapedia`) append under their own keys in the same file.
    `audit-apply --auto` and `--review` both honour `# manual: true` (line 1);
    `--review` prepends the marker so operator values survive future bootstrap runs.
21. **TCGCollector has no `name_ja`** — `audit-diff` always emits `NO_ORACLE` for those
    rows. Phase 4 (`audit-fallback --field name_ja`) uses the Pokellector JPN field.
    Don't extend `tcgcollector_client.py` for JA names; they're not on the page.
22. **When adding a new audit oracle,** register its slug in `data/sets/<SET>.yml` and
    update `seed_sets._normalize`. Add canonicalization to `rarities.py` if needed.
24. **All price display must go through `formatPrice` from `useCurrency()`.**
    Never call `formatJPY` directly in components — it bypasses the currency
    toggle. `formatJPY` is an internal helper used only inside `formatPrice`.
    Every component that shows a JPY value (including set total values) must
    call `useCurrency()` and use the returned `formatPrice` bound function.
25. **`CurrencyProvider` must sit inside `QueryClientProvider`** so
    `useExchangeRates()` (which calls `useQuery`) can work. The order in
    `main.tsx` is: `StrictMode` → `QueryClientProvider` → `CurrencyProvider`
    → `App`. Don't invert these.
26. **`CardThumbnail` uses a runtime type guard to skip individual
    `useMarketPrice` calls when price is already embedded.** The `isSearchResult`
    guard detects `market_price_jpy` and calls `useMarketPrice` with `enabled: false`.
    Don't break the `enabled` param on `useMarketPrice` — pass `!hasEmbedded` when
    price data is already available on the card object.
27. **`graded_price_points` is fed by SNKRDUNK (primary) and Cardrush (secondary).** SNKRDUNK's sales-history feed includes graded strings (`"PSA10"`, `"PSA9"`, `"BGS9.5"`) alongside ungraded entries; the parser splits them. `"PSA8以下"` and `"BGS10 BL"` are silently dropped. Cardrush graded listings use `【PSA10】` brackets — captured via `extract_cardrush_grade` + `parse_grade_company_score`. `GradeCompany` covers PSA/BGS/CGC only; SGC deferred (`parse_grade_company_score("SGC10")` → `None`).
28. **No MV for graded prices.** Both `/graded-prices` and `/graded-history` read directly from `graded_price_points`. If volume grows, add an MV for the "latest per grade+source" query.
29. **Promo set_codes must be hyphen-free** — `parse_artwork_id` / `parse_card_id` split on `-` and assume 3/4 segments. M-P promos use internal `MP`, SM-P use `SMPR`, S-P use `SP`, SV-P use `SVP`. The SNKRDUNK product-number era CAN have hyphens (it's separate from set_code); the override map `_SNKRDUNK_ERA_SLUG_OVERRIDE` in `watari_snkrdunk/run.py` translates `SMPR → sm-p`, etc. Cardrush promo search uses `_CARDRUSH_PROMO_KEYWORD` and routes through `scrape_promo_set` (not `scrape_set`).
30. **Cardrush promo routing in `__main__.py` is automatic.** When `--set MP` (or SMPR/SP/SVP) is passed, the dispatcher calls `scrape_promo_set` instead of `scrape_sets`. The CLI flag `--rarity` is ignored for promo sets (promos have no rarity-bucket loop). Classic sets (CLF/CLL/CLK) route through the normal `scrape_set` path.
31. **`bootstrap-set` auto-routes to TCGCollector-primary** when a set has `tcgcollector_id`+`tcgcollector_slug` in its YAML but no `pokellector_slug`. The function `bootstrap_set_from_tcgcollector` handles the 7 new sets (CLF/CLL/CLK/MP/SMPR/SP/SVP). Source precedence: name_en/rarity/illustrator from TCGCollector detail, image_url from TCGCollector grid tile, name_ja from TCGdex or Cardrush. Promo cards get `rarity_code: PR` (mapped via `canonicalize_tcgcollector("Promo")`).
32. **TCGCollector promo set URLs** use a different trailing format: `/cards/{id}/slug-{local_id}-{series}` (e.g. `001-m-p`) instead of `/cards/{id}/slug-{local_id}-{total}` (e.g. `001-032`). The `_INDEX_LINK_RE` regex handles both. The `set_total` field on `TcgCollectorIndexEntry` is `None` for promo sets. Do not tighten the regex back to `(\d+)-(\d+)$`.
33. **Online mode: the API has no DB session.** `deps.py` now exposes `get_catalog` (returns `app.state.catalog: MemCatalog`) and `get_price_proxy` (returns `app.state.price_proxy: PriceProxy`). There is no `get_session`. Do not add `SessionDep` or SQLAlchemy imports back to routers without also re-wiring the lifespan and dependencies.
34. **`PriceProxy` is the sole I/O layer in online mode.** It reuses the existing `CardrushClient` / `SnkrdunkClient` — no new HTTP clients. The 30-min TTL cache is keyed on `(set_code, local_id)`. Do not bypass it by calling the scrapers directly from routers.
35. **`MemCatalog` is loaded once at lifespan startup and never mutated.** To reflect new catalog data (after a `make catalog-seed-*` run) the process must restart. Do not attempt live-reload of the in-memory catalog without also resetting the `PriceProxy` cache.
36. **CI scraper schedule is disabled.** `.github/workflows/scrape.yml` has no `schedule:` trigger — only `workflow_dispatch`. Scrapers still work (packages unchanged); re-enable via `on.schedule` when PostgreSQL is restored.

---

## 7. Common commands

```bash
# Bring up infra
make up                      # postgres + minio
make migrate                 # alembic upgrade head
make bronze-setup-lifecycle  # install 90-day expiry rule on bronze bucket (once per bucket)

# Catalog (metadata pipeline)
make catalog-seed-sets                       # load data/sets/*.yml → sets
make catalog-bootstrap SET=SV2A              # Pokellector+TCGdex+Cardrush → data/cards/
make catalog-seed-cards                      # YML tree → artworks + cards
make catalog-seed-cards SET=SV2A             # single set
make catalog-verify                          # health snapshot (orphans, missing img/rarity/ja)
make catalog-verify STRICT=1                 # exit non-zero on null name_ja / rarity in non-promo sets
make catalog-verify-pokellector              # cross-check local IDs vs live jp.pokellector.com (network)

# --- Catalog data-quality audit (TCGCollector-anchored) ---
# Phase 1: per-set markdown gap report (no data changes).
make catalog-audit                           # all sets, writes reports/catalog-audit-*.md
make catalog-audit SET=SV4A                  # single set

# Phase 2: scrape TCGCollector → data/audit/<SET>.yml (curl_cffi, bronze mirror).
make catalog-audit-fetch SET=SV4A

# Phase 3: diff data/audit vs data/cards → reports/audit-diff-*.md|.tsv.
make catalog-audit-diff                      # all sets with audit data
make catalog-audit-diff SET=SV4A             # single set

# Phase 4: fallback oracles (Pokellector JPN for name_ja, TODO TSV for others).
uv run python -m watari_catalog audit-fallback --set SV4A --field name_ja
uv run python -m watari_catalog audit-fallback --set SV4A --field illustrator

# Phase 5: apply oracle values to data/cards/<SET>/<NNN>.yml.
make catalog-audit-apply TSV=reports/audit-diff-SV4A-*.tsv MODE=auto      # AUTO_FILL only
make catalog-audit-apply TSV=reports/audit-diff-SV4A-*.tsv MODE=review    # operator-edited

# Phase 6: one-shot rollout per set (fetch → diff → auto-apply → re-seed DB).
make catalog-audit-rollout SET=SV4A
make sync-set-symbols                        # rebuild SET_SYMBOL_URLS in apps/web from Bulbapedia export
make sync-set-symbols SYMBOLS_MD=/path/to/List_of_...md

# Prices (scrapers auto-refresh the price MVs on completion)
make scrape-cardrush SET=SV2A                # one set
make scrape-cardrush ERA=SV                  # all sets in era (SV | ME | SM | SW)
make scrape-snkrdunk ERA=sv2a                # one era slug

# API (read layer — online mode, no DB or Redis required)
make api                                     # prod: 0.0.0.0:8000
make api-dev                                 # dev: 127.0.0.1:8000, reload
curl "http://127.0.0.1:8000/jp/cards/SV2A/089/prices?variant=normal"
# Note: first request per card takes 2–5 s (live scrape); cached 30 min thereafter.
# Key-management (create-key/revoke-key/list-keys) and refresh-mvs removed in online mode.

# Frontend (Vite + React)
make web-install                             # bun install
make web-dev                                 # dev server (VITE_API_BASE_URL=http://127.0.0.1:8000)
make web-build                               # production build
# Copy apps/web/.env.example → apps/web/.env.local and set VITE_API_BASE_URL

# Fly.io production ops
make deploy                                  # fly deploy --remote-only
make migrate-prod                            # fly ssh console → alembic upgrade head
make refresh-mvs-prod                        # fly ssh console → watari-api refresh-mvs
make logs                                    # fly logs -a watari-api
make ssh                                     # fly ssh console -a watari-api

# Deployment helpers (data dump / prod bootstrap)
make db-dump-data                            # data-only dump for prod rollout
CONFIRM=yes DUMP_FILE=/tmp/watari-data-<UTC>.sql.gz make db-prod-bootstrap

# Dev loop
make test                                    # 376 tests
make lint
make format

# Manual inspection
uv run python -m watari_catalog bootstrap-set --set SV2A --help
uv run python -m watari_cardrush --set SV2A --rarity SAR --max-pages 1
```

---

## 8. Reference docs

- `plans/catalog-metadata.md` — original catalog v1/v2 design
- `plans/catalog-v3-yml-contract.md` — the v3 split we just shipped
- `plans/cardrush-scraper-rewrite.md` — `curl_cffi` rewrite (already done)
- `plans/iterative-zooming-walrus.md` — localization ideas (not yet started)

## 9. How to extend this file

- When you **migrate the DB**, add a row under §3.1 and bump the revision.
- When you **add a new source**, update §3.2 (flow) + §3.3 (precedence table).
- When you **finish a roadmap item**, move it from §5 to §4 with a note on
  the smoke results and commit/run date.
- When you **discover a new gotcha**, add it to §6 so the next session doesn't
  rediscover it the hard way.

## 10. Production deployment

Schema from Alembic, catalog re-seeded from YML, only price history dumped.
Excluded from dump: `api_keys`, MVs, `alembic_version`.

### Scripts

- `scripts/dump_prod_data.sh`
  - Uses `docker compose exec -T postgres pg_dump ... --data-only`
  - Dumps only `price_points`, `card_scrape_state`, `scrape_runs`
  - Writes `dumps/watari-data-<UTC>.sql.gz`
- `scripts/prod_bootstrap.sh`
  - Requires `CONFIRM=yes` and `DUMP_FILE=/abs/path/to/sql_or_sql.gz`
  - Runs:
    1. `make migrate`
    2. `make catalog-seed-sets`
    3. `make catalog-seed-cards`
    4. `psql "$DATABASE_URL" -f <dump>`
    5. `uv run watari-api refresh-mvs`
  - Fails fast if `DATABASE_URL` is missing.

### Rollout runbook

```bash
# On source environment (dockerized local/staging)
make db-dump-data
scp dumps/watari-data-<UTC>.sql.gz prod:/tmp/

# On production host
export DATABASE_URL=postgresql://...
CONFIRM=yes DUMP_FILE=/tmp/watari-data-<UTC>.sql.gz make db-prod-bootstrap
uv run watari-api create-key --owner ops@example.com --tier admin
```
