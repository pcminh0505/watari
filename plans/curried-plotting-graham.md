# Graded Card (Slab) Price Tracker — Data Layer

## Context

The project currently tracks ungraded Pokémon card prices (conditions A/A-/B/C) from Cardrush
(listings) and SNKRDUNK (sold comps). Graded card slabs (PSA/BGS/CGC) command a separate
premium market and are not tracked at all today.

**Key finding from investigation:**
- **Cardrush** already detects graded product names via `【PSA10】`/`【BGS9.5】`/`【CGC10】`
  regex in `conditions.py::parse_cardrush_condition()` — but returns `is_graded=True` and the
  parser immediately drops those rows. This is free data we are throwing away.
- **SNKRDUNK** API (sales-history) only returns raw conditions S/A/B/C. It is unknown whether
  SNKRDUNK has a separate product namespace or endpoint for certified slabs.

This plan scopes to **data layer only** (no frontend chart). The Collectr-style multi-line
graded price history chart is a follow-up frontend session once the data is flowing.

Graders in scope: **PSA, BGS, CGC** (SGC deferred).

---

## Phase 0 — Investigate SNKRDUNK Graded Namespace (manual, first step)

Before touching code, probe SNKRDUNK to determine if graded data is accessible.

**Steps:**
1. Browse `snkrdunk.com` for a high-value graded JP card (e.g. PSA 10 SV2A Kingdra ex).
2. On the product page, check if the URL or API request contains a different product number
   format (e.g. `pkmn-tcg-psa10-sv2a-089` or a dedicated `certified-cards` namespace).
3. Try `GET https://snkrdunk.com/v1/apparels?productNumber=<candidate>` with the Watari
   SNKRDUNK client for several candidate formats.
4. Check the sales-history response for any sold certified listings.

**Outcomes:**
- If SNKRDUNK has a graded namespace → add a second scraper path (Phase 3b below).
- If SNKRDUNK has no graded data → Cardrush listings are the sole source for this release.

---

## Phase 1 — Schema Migration (`008_graded_price_points`)

Create a separate table to avoid any impact on `price_points` and the four existing MVs.

**File:** `migrations/versions/008_graded_price_points.py`

```sql
CREATE TABLE graded_price_points (
    id            BIGSERIAL PRIMARY KEY,
    card_id       TEXT NOT NULL REFERENCES cards(card_id),
    source        TEXT NOT NULL,           -- 'cardrush' | 'snkrdunk'
    source_type   TEXT NOT NULL,           -- 'listing' (CR) | 'sold' (SD, if found)
    grade_company TEXT NOT NULL,           -- 'PSA' | 'BGS' | 'CGC'
    grade_score   NUMERIC(3,1) NOT NULL,   -- 10.0 | 9.5 | 9.0 | 8.0 | ...
    price_jpy     INTEGER NOT NULL,
    stock_qty     INTEGER,                 -- NULL for sold comps
    observed_at   TIMESTAMPTZ NOT NULL,
    external_url  TEXT,
    scrape_run_id BIGINT REFERENCES scrape_runs(id),
    created_at    TIMESTAMPTZ DEFAULT now(),

    UNIQUE(card_id, source, grade_company, grade_score, price_jpy, observed_at,
           COALESCE(external_url, ''))
);

CREATE INDEX ON graded_price_points(card_id, grade_company, grade_score, observed_at DESC);
```

**Why separate table (not extending `price_points`):**
- The four existing MVs (`mv_latest_price`, `mv_median_7d`, `mv_cross_source_spread`,
  `mv_market_price`) query `price_points` directly. Adding nullable grade columns would require
  updating all four MV definitions and their unique indexes.
- Graded pricing is a distinct concept; keeping it separate makes both tables simpler.

---

## Phase 2 — Core: GradeCompany Enum & Parse Helper

**File:** `packages/core/watari_core/conditions.py`

Add after the existing `Condition` enum and Cardrush/SNKRDUNK maps:

```python
class GradeCompany(StrEnum):
    PSA = "PSA"
    BGS = "BGS"
    CGC = "CGC"

# e.g. "PSA10" → (GradeCompany.PSA, 10.0)
# e.g. "BGS9.5" → (GradeCompany.BGS, 9.5)
_GRADE_RE = re.compile(r"^(PSA|BGS|CGC)(\d+(?:\.\d+)?)$", re.IGNORECASE)

def parse_grade_company_score(raw: str) -> tuple[GradeCompany, float] | None:
    """Return (company, score) if raw is a recognised grade string, else None."""
    m = _GRADE_RE.match(raw.strip())
    if not m:
        return None
    try:
        company = GradeCompany(m.group(1).upper())
        score = float(m.group(2))
        return (company, score)
    except (ValueError, KeyError):
        return None
```

Note: Cardrush product names use `【PSA10】` — the Cardrush parser already extracts the
inner string (`PSA10`) via `_GRADED_RE`. `parse_grade_company_score("PSA10")` handles that.

---

## Phase 3a — Core: SQLAlchemy Model & Pydantic Schema

**File:** `packages/core/watari_core/models.py`

Add `GradedPricePoint` ORM class (mirrors the migration DDL above).

Key fields: `card_id`, `source`, `source_type`, `grade_company`, `grade_score`,
`price_jpy`, `stock_qty`, `observed_at`, `external_url`, `scrape_run_id`.

**File:** `packages/core/watari_core/schemas.py`

Add:
```python
class GradedPricePointCreate(BaseModel):
    card_id: str
    source: str
    source_type: str
    grade_company: str
    grade_score: float
    price_jpy: int
    stock_qty: int | None
    observed_at: datetime
    external_url: str | None
    scrape_run_id: int | None
```

**File:** `packages/core/watari_core/ingestion.py`

Add `upsert_graded_price_points(session, rows: list[GradedPricePointCreate]) -> int`
following the same bulk-upsert pattern as the existing `upsert_price_points()`.

---

## Phase 3b — Cardrush Parser: Capture Graded Rows

**File:** `packages/scraper_cardrush/watari_cardrush/parser.py`

Currently when `is_graded=True` the row is skipped with `continue`. Change to:
- Extract the grade string from the `【…】` token (already captured by `_GRADED_RE`)
- Call `parse_grade_company_score(grade_str)` from core `conditions.py`
- If it returns a valid `(company, score)`, build a `GradedPricePointCreate` row and
  append it to a separate `graded` output list
- Return `(ungraded_rows, graded_rows)` from the parser function (or use a named tuple)

**File:** `packages/scraper_cardrush/watari_cardrush/run.py`

Receive `graded_rows` from the parser and call `upsert_graded_price_points(session, graded_rows)`.
Count towards `rows_written` separately (or add a `graded_rows_written` counter to the run
metadata JSONB — does not need a schema change).

---

## Phase 3c — SNKRDUNK Scraper (conditional on Phase 0 findings)

If Phase 0 confirms SNKRDUNK has a graded product namespace:

**File:** `packages/scraper_snkrdunk/watari_snkrdunk/client.py`
- Add `resolve_graded_apparel_id(card_id, grade_company, grade_score)` method probing
  candidate product number formats.

**File:** `packages/scraper_snkrdunk/watari_snkrdunk/run.py`
- After scraping raw cards, optionally scrape graded products and write to
  `graded_price_points` via `upsert_graded_price_points()`.

If Phase 0 shows no SNKRDUNK graded data, this phase is skipped.

---

## Phase 4 — API Endpoints

**File:** `packages/api/watari_api/schemas.py`

```python
class GradedPricePointOut(BaseModel):
    id: int
    card_id: str
    source: str
    source_type: str
    grade_company: str
    grade_score: float
    price_jpy: int
    observed_at: datetime
    external_url: str | None

class LatestGradedPrice(BaseModel):
    grade_company: str
    grade_score: float
    source: str
    price_jpy: int
    observed_at: datetime
```

**File:** `packages/api/watari_api/routers/prices.py`

Add two new routes (reuse the existing `resolve_card_id` helper and `SessionDep`):

```
GET /{lang}/cards/{set_code}/{local_id}/graded-prices
    ?variant=normal
    → list[LatestGradedPrice]   (most recent row per grade_company+grade_score)

GET /{lang}/cards/{set_code}/{local_id}/graded-history
    ?variant=normal
    &days=365          (int 1-365, default 365)
    &company=PSA       (optional: PSA | BGS | CGC)
    &limit=2000
    → list[GradedPricePointOut]  (sorted observed_at DESC)
```

Both endpoints read directly from `graded_price_points` (no MV needed at this stage —
graded data volume will be much smaller than ungraded).

---

## Phase 5 — Tests

| File | What to add |
|------|-------------|
| `tests/unit/test_conditions.py` | `TestParseGradeCompanyScore`: valid cases (PSA10, BGS9.5, CGC10), invalid (unknown company, no score, empty) |
| `tests/unit/test_cardrush_parser.py` | Verify graded product names return `GradedPricePointCreate` rows instead of being dropped; ungraded rows unaffected |
| `tests/unit/test_api.py` | Endpoint shape tests for `graded-prices` and `graded-history` using `FakeSession` override |

Target: existing 232 tests continue to pass; add ~15 new tests.

---

## TypeScript types (CLAUDE.md update only — no UI built yet)

When the frontend chart session begins, add to `src/types/api.ts`:
```typescript
interface GradedPricePointOut {
  id: number;
  card_id: string;
  source: string;
  source_type: string;
  grade_company: string;   // "PSA" | "BGS" | "CGC"
  grade_score: number;     // 10.0, 9.5, 9.0 ...
  price_jpy: number;
  observed_at: string;
  external_url: string | null;
}
```
Hook: `useGradedHistory(setCode, localId, variant, days?, company?)`.

---

## Verification

```bash
# 1. Migration
alembic upgrade head
# → graded_price_points table + index created, no errors

# 2. Smoke scrape (Cardrush, single set)
make scrape-cardrush SET=SV2A
# → check logs for "graded_rows_written: N" in scrape_runs.metadata

# 3. Inspect captured data
psql $DATABASE_URL -c "
  SELECT grade_company, grade_score, COUNT(*), AVG(price_jpy)::int
  FROM graded_price_points
  GROUP BY 1, 2 ORDER BY 1, 2;"

# 4. API
curl "http://127.0.0.1:8000/jp/cards/SV2A/089/graded-prices?variant=normal"
curl "http://127.0.0.1:8000/jp/cards/SV2A/089/graded-history?variant=normal&days=365"

# 5. Full test suite
uv run pytest
# → 247+ tests pass (232 existing + ~15 new)

# 6. SNKRDUNK investigation (manual, before Phase 3c)
# Probe snkrdunk.com for graded card product numbers on a known PSA 10 card
```

---

## Files changed / created

| File | Action |
|------|--------|
| `migrations/versions/008_graded_price_points.py` | Create |
| `packages/core/watari_core/conditions.py` | Edit — add `GradeCompany`, `parse_grade_company_score` |
| `packages/core/watari_core/models.py` | Edit — add `GradedPricePoint` ORM model |
| `packages/core/watari_core/schemas.py` | Edit — add `GradedPricePointCreate` |
| `packages/core/watari_core/ingestion.py` | Edit — add `upsert_graded_price_points()` |
| `packages/scraper_cardrush/watari_cardrush/parser.py` | Edit — return graded rows instead of dropping |
| `packages/scraper_cardrush/watari_cardrush/run.py` | Edit — write graded rows to new table |
| `packages/api/watari_api/schemas.py` | Edit — add `GradedPricePointOut`, `LatestGradedPrice` |
| `packages/api/watari_api/routers/prices.py` | Edit — add `/graded-prices` + `/graded-history` |
| `tests/unit/test_conditions.py` | Edit — add grade parse tests |
| `tests/unit/test_cardrush_parser.py` | Edit — add graded-row capture tests |
| `tests/unit/test_api.py` | Edit — add endpoint shape tests |

**Not changed:** `price_points`, all four MVs, SNKRDUNK raw-card scraper (unless Phase 0 finds data).
