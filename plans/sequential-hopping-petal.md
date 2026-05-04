# Plan: Legacy-Era Support Hardening

## Context

After expanding the catalog from 30 sets (SV + ME) to 98 sets (adding 37 SM and 30 SWSH sets), several systemic gaps surfaced. The SM/SW era adds new rarity labels Pokellector has never used for SV-era sets, which breaks the rarity pipeline in a cascading way: null `rarity_code` → `_load_rarities()` skips those cards → Cardrush never scrapes them. In parallel, the frontend has incomplete rarity sort positions for SM/SW codes, the SNKRDUNK era slug casing for legacy sets is unverified, there is no unified price signal, and there is no visibility into scrape health across 98 sets. This plan organizes the fixes into four pillars, in priority order.

---

## Pillar 1 — Catalog Rarity Quality (highest priority)

### Problem
- **388 null `rarity_code` values** across SM/SW sets caused by three unmapped Pokellector labels:
  - `"Secret Rare"` → 304 cards (SM8B, S1W, S8B, and others)
  - `"Shiny"` → 69 cards (S4A, S8B VMAX Climax)
  - `"Prism Star"` → 15 cards (SM-era ◇ cards)
- `_load_rarities()` in `packages/scraper_cardrush/watari_cardrush/run.py:89` skips cards with null `rarity_code` — so those cards are invisible to the Cardrush scraper entirely.
- Frontend `RARITY_SORT_ORDER` in `apps/web/src/lib/constants.ts` is missing SM/SW era codes: `CHR`, `CSR`, `SSR`, `HR`, `TR`, `K` — causing wrong rarity sort order.

### Approach

**Step 1 — Fix `rarities.py`**

File: `packages/catalog/watari_catalog/rarities.py`

Add to `POKELLECTOR_RARITY_MAP`:
```python
"Secret Rare":  "UR",   # SM/SW gold/rainbow + secret alt-arts
"Shiny":        "SR",   # SWSH Shiny Star V / VMAX Climax shiny tier
"Prism Star":   "SR",   # SM-era ◇ prism cards
```

Verify existing entries still cover:
- `"Rare Holo"` → `"R"` (SW era holo rares should not be overridden)
- `"Ultra Rare"` → `"UR"` already present; `"Secret Rare"` now also → `"UR"` is consistent

**Step 2 — Update tests**

File: `tests/unit/test_catalog_rarities.py`

Add parameterized test cases for the three new mappings.

**Step 3 — Re-bootstrap affected sets**

Run `make catalog-bootstrap SET=<code>` for every SM/SW set that has null rarity cards. The bootstrap re-merges sources using the updated `POKELLECTOR_RARITY_MAP`; only changed YMLs are written (unchanged ones skipped). Affected sets include at minimum: SM8B, S1W, S8B, S4A, and all SM-era sets with Prism Star cards (SM7B, SM8, SM9, SM10, SM10A, SM11).

After bootstrap: run `make catalog-seed-cards` to propagate new rarity_codes to the DB.

**Step 4 — Fix frontend `RARITY_SORT_ORDER`**

File: `apps/web/src/lib/constants.ts`

Add the missing SM/SW era codes, slotted into the existing ladder:
```ts
// existing: C=0, U=1, R=2, RR=3, PR=4, RRR=5, SR=6, AR=7, SAR=8, UR=9, MUR=10
TR:  3,   // Trainer Gallery Rare (SW era full-art trainers)
K:   4,   // Radiant Rare (SW era)
CHR: 5,   // Character Rare (SW era)
CSR: 6,   // Character Super Rare (SW era)
SSR: 7,   // Shiny Double Rare (SW era)
HR:  7,   // Hyper Rare (SM era gold; equivalent rarity tier to AR)
```

### Files changed
- `packages/catalog/watari_catalog/rarities.py`
- `tests/unit/test_catalog_rarities.py`
- `apps/web/src/lib/constants.ts`
- YML changes in `packages/catalog/data/cards/{SM/SW sets}/*.yml` (generated)

### Verification
```bash
make test                              # confirm test_catalog_rarities passes
make catalog-bootstrap SET=SM8B        # should yield 0 null rarity_codes for SM8B
make catalog-bootstrap SET=S1W
make catalog-seed-cards
# Confirm in DB:
# SELECT rarity_code, COUNT(*) FROM artworks WHERE set_code='SM8B' GROUP BY 1;
# → no null rows
```

---

## Pillar 2 — Scraper Correctness for SM/SW Eras

### Problem
- **SNKRDUNK era case sensitivity (unverified):** `resolve_apparel(era, local_id)` in `packages/scraper_snkrdunk/watari_snkrdunk/client.py:50` builds `product_number = f"pkmn-tcg-{era}-{local_id}"`. The CI `snkrdunk-legacy` matrix uses lowercase slugs (`sm8b`, `s1w`, etc.). CLAUDE.md confirms ME-era product numbers are `pkmn-tcg-M1L-NNN` (uppercase). Whether SNKRDUNK is case-insensitive is untested for SM/SW.
- **Cardrush keyword format untested for SM/SW:** `_crawl_rarity` in `packages/scraper_cardrush/watari_cardrush/run.py:126` searches `f"{set_code} {rarity_code}"`. Not known whether Cardrush search returns results for `"SM8B UR"` or `"S1W SR"`.
- **Null-rarity gap:** resolved as a consequence of Pillar 1. After Pillar 1 lands, `_load_rarities()` will include newly-assigned codes and scraping will resume for those cards automatically.

### Approach

**Step 1 — Verify SNKRDUNK casing with a dry-run probe**

Before the first weekly CI run, run a targeted probe:
```bash
# Test with lowercase (current CI behavior)
uv run python -m watari_snkrdunk --era sm8b --limit 1

# Test with uppercase
uv run python -m watari_snkrdunk --era SM8B --limit 1
```

If lowercase returns `not_found=N` and uppercase returns `succeeded=1`, the CI matrix slugs are wrong.

**Step 2 — Fix `resolve_apparel` if case-sensitive**

File: `packages/scraper_snkrdunk/watari_snkrdunk/client.py`

If SNKRDUNK is case-sensitive and requires uppercase for legacy eras, change:
```python
product_number = f"pkmn-tcg-{era.upper()}-{local_id.split('/')[0]}"
```

If SNKRDUNK is truly case-insensitive (lowercased SV slugs work), no code change is needed, only CI matrix verification.

**Step 3 — Verify Cardrush dry-run for legacy sets**

```bash
uv run python -m watari_cardrush --set SM8B --rarity UR --dry-run --max-pages 2
uv run python -m watari_cardrush --set S1W --rarity SR --dry-run --max-pages 2
```

Check that `listings_dropped_wrong_set` is low and `listings_seen > 0`. If Cardrush doesn't recognize the set code, the disambiguation filter will drop everything.

**Step 4 — Update CI matrix if casing is wrong**

File: `.github/workflows/scrape.yml`

Update `snkrdunk-legacy` matrix era entries to use the correct casing discovered in Step 1.

### Files potentially changed
- `packages/scraper_snkrdunk/watari_snkrdunk/client.py` (if case fix needed)
- `.github/workflows/scrape.yml` (if CI matrix casing is wrong)

### Verification
```bash
# After fix:
uv run python -m watari_snkrdunk --era SM8B --limit 5   # should return succeeded > 0
uv run python -m watari_cardrush --set SM8B --rarity UR --dry-run --max-pages 2
# Check scrape_runs table for rows_written > 0
```

---

## Pillar 3 — Unified Price Signal

### Problem
- The current thumbnail price logic (`CardThumbnail.tsx:18-25`) is ad-hoc: prefer cardrush condition A → any condition A → min price. This can show a Cardrush listing price or a SNKRDUNK sold price with no label. For SM/SW sets with no Cardrush data, it falls back to something confusing.
- There is no single "market price" per card in the API.
- `total_value_jpy` on `SetOut` sums `mv_latest_price` per set — for SM/SW sets (no price data yet) this is null/0, making "Sort by value" useless for legacy sets.

### Approach

**Step 1 — New Alembic migration `007_mv_market_price`**

File: `migrations/versions/007_mv_market_price.py`

Create `mv_market_price` view:
```sql
-- One row per (card_id, condition='A').
-- market_price_jpy: SNKRDUNK 7-day median if available,
--                   else Cardrush condition-A floor.
-- source_used: 'snkrdunk' | 'cardrush'
CREATE MATERIALIZED VIEW mv_market_price AS
SELECT
    COALESCE(sd.card_id, cr.card_id)  AS card_id,
    COALESCE(sd.median_7d,  cr.price) AS market_price_jpy,
    CASE WHEN sd.card_id IS NOT NULL THEN 'snkrdunk' ELSE 'cardrush' END AS source_used
FROM (
    SELECT card_id, price_jpy AS median_7d
    FROM mv_median_7d
    WHERE source = 'snkrdunk' AND condition = 'A'
) sd
FULL OUTER JOIN (
    SELECT card_id, price_jpy AS price
    FROM mv_latest_price
    WHERE source = 'cardrush' AND condition = 'A'
) cr ON sd.card_id = cr.card_id;

CREATE UNIQUE INDEX uq_mv_market_price_card_id ON mv_market_price (card_id);
```

Per invariant #15: the UNIQUE index is created in the same migration so `CONCURRENTLY` works.

**Step 2 — Add to `mvs.py` refresh list**

File: `packages/core/watari_core/mvs.py`

Add `mv_market_price` as the 4th MV in `refresh_price_mvs`. Order:
`mv_latest_price` → `mv_median_7d` → `mv_cross_source_spread` → `mv_market_price`

**Step 3 — Add schema + API endpoint**

File: `packages/core/watari_core/schemas.py`
```python
class MarketPriceOut(BaseModel):
    card_id: str
    market_price_jpy: int
    source_used: str   # 'snkrdunk' | 'cardrush'
```

File: `packages/api/watari_api/routers/prices.py`

Add endpoint:
```
GET /{lang}/cards/{set_code}/{local_id}/market-price?variant=normal
→ MarketPriceOut | 404
```

Reads from `mv_market_price` via `card_id` lookup (same pattern as existing `/prices` endpoint).

**Step 4 — Update `_set_values_map` to use `mv_market_price`**

File: `packages/api/watari_api/routers/sets.py`

Switch `_set_values_map` to sum from `mv_market_price` instead of `mv_latest_price`. This makes `total_value_jpy` use the best available price signal per card.

**Step 5 — Update frontend**

File: `apps/web/src/api/prices.ts` — add `useMarketPrice(set_code, local_id, variant)` hook.

File: `apps/web/src/types/api.ts` — add `MarketPriceOut` interface.

File: `apps/web/src/components/cards/CardThumbnail.tsx` — replace the ad-hoc price logic with `useMarketPrice`. Show a small source label (`↗` for sold, `⊙` for listed) or color-code the price text.

### Files changed
- `migrations/versions/007_mv_market_price.py` (new)
- `packages/core/watari_core/mvs.py`
- `packages/core/watari_core/schemas.py`
- `packages/api/watari_api/routers/prices.py`
- `packages/api/watari_api/routers/sets.py`
- `apps/web/src/api/prices.ts`
- `apps/web/src/types/api.ts`
- `apps/web/src/components/cards/CardThumbnail.tsx`
- `tests/unit/test_mvs.py` — add test for 4-MV refresh list

### Verification
```bash
make migrate
uv run watari-api refresh-mvs
curl "http://127.0.0.1:8000/jp/cards/SV2A/089/market-price?variant=normal"
# → {"card_id":"jp-sv2a-089-normal","market_price_jpy":50,"source_used":"snkrdunk"}
make test   # test_mvs.py must pass with 4 MVs
```

---

## Pillar 4 — Scrape Health Dashboard

### Problem
With 98 sets and weekly CI runs, failures are invisible: a set returning 0 rows (like the historical M1/M1L case) is silently swallowed. `scrape_runs` and `card_scrape_state` tables contain all the needed data but nothing surfaces it.

### Approach

**Step 1 — New API endpoint `GET /admin/scrape-health`**

File: `packages/api/watari_api/routers/admin.py` (new)

Returns per-set health summary. No auth required (internal tool), or gated to `admin` tier at discretion.

Response shape (`ScrapeHealthRow`):
```python
class ScrapeRunSummary(BaseModel):
    started_at: datetime | None
    status: str | None          # 'ok' | 'running' | 'error'
    rows_written: int
    cards_failed: int           # count of card_scrape_state rows with consecutive_failures > 0

class ScrapeHealthRow(BaseModel):
    set_code: str
    era_block: str
    cardrush: ScrapeRunSummary
    snkrdunk: ScrapeRunSummary
    warning: str | None         # 'zero_rows' | 'consecutive_failures' | 'stale_7d' | None
```

Query logic:
- Join `scrape_runs` (latest per set+source from `metadata_->>'era'` or by inferring set from run metadata) with `card_scrape_state` aggregate.
- `zero_rows` warning: latest run `rows_written == 0` and set has tracked cards.
- `stale_7d` warning: latest run `finished_at < now() - interval '7 days'`.

Register router in `packages/api/watari_api/main.py` under `/admin`.

**Step 2 — Frontend `/admin` page**

File: `apps/web/src/pages/AdminPage.tsx` (new)

A simple table view:
- Columns: Set | Era | Cardrush (date + rows, colored) | SNKRDUNK (date + rows, colored) | Warning badge
- Color coding: green (ok), yellow (zero_rows/stale), red (consecutive_failures/error)
- Era filter pills (reuse `SetsFilterBar` era pill pattern)
- No authentication for dev; add a notice that this is an internal page

File: `apps/web/src/api/admin.ts` (new) — `useScrapHealth()` hook.

File: `apps/web/src/App.tsx` — add `/admin` route.

### Files changed
- `packages/api/watari_api/routers/admin.py` (new)
- `packages/api/watari_api/main.py`
- `packages/core/watari_core/schemas.py`
- `apps/web/src/pages/AdminPage.tsx` (new)
- `apps/web/src/api/admin.ts` (new)
- `apps/web/src/App.tsx`

### Verification
```bash
make api-dev &
curl http://127.0.0.1:8000/admin/scrape-health | python3 -m json.tool
# → list of ScrapeHealthRow, SM/SW sets show warning: "stale_7d" (no data yet)
# Open http://localhost:5173/admin → table renders, era filter works
make test
```

---

## Execution Order

Each pillar is independent except the noted dependency:

```
Pillar 1 (Rarity fix)      ← start here; unblocks Cardrush scraping
  ↓ cascades to
Pillar 2 (Scraper probe)   ← can run in parallel with Pillar 1 verification
Pillar 3 (Price signal)    ← independent; requires DB running for migration
Pillar 4 (Dashboard)       ← independent; can be done last
```

Pillar 1 must be fully verified (bootstrap + seed complete, null rarity_codes = 0 for affected sets) before running the first legacy Cardrush scrape.

## Open Questions / Risks

1. **SNKRDUNK casing for SM/SW:** If `pkmn-tcg-sm8b-001` doesn't resolve, the fix is simple but requires one manual probe run before committing. This is the highest-risk unknown — see Pillar 2 Step 1.
2. **Prism Star → SR accuracy:** 15 cards. If a future decision is to give Prism Star its own code (`PS`), `rarities.py` and `RARITY_SORT_ORDER` need one additional entry. The mapping is trivially reversible.
3. **`mv_market_price` join edge cases:** Cards with SNKRDUNK median but no Cardrush listing, and vice versa. The `FULL OUTER JOIN` handles this but the `UNIQUE` index on `card_id` requires no row duplication — verify SQL produces exactly one row per card.
4. **`scrape_runs.metadata_` contains era, not set_code:** The admin health endpoint will need to match runs to sets via the `metadata_->>'era'` JSON field, which is a per-scraper convention. Verify the metadata shape for both cardrush and snkrdunk runs before writing the SQL.
