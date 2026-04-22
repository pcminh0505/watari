# Plan — Cardrush scraper rewrite (Playwright → curl_cffi)

**Status**: draft, deferred until `catalog-metadata.md` is implemented.
**Depends on**: `catalog-metadata.md` (this plan assumes the new `cards`/`sets` schema with `variant` + `rarity_code` is in place).
**Replaces**: current `packages/scraper_cardrush` (Playwright-based, per-card keyword loop).

---

## Motivation

The existing scraper has three compounding problems:

1. **Browser launch per run is heavy.** Playwright + Chromium adds ~4 GB of setup (`playwright install chromium`), ~1 GB RAM at runtime, and ~3–5 s of cold start per search. `headless=False` is required to pass Cloudflare today, making the scraper unsuitable for containers/CI.
2. **Per-card keyword search is O(cards).** 210 cards per set → 210 page loads. For a typical era that's 10–30 minutes of wall-clock per set.
3. **Cloudflare posture has been probed empirically and does not require a browser.** `curl_cffi` with Chrome TLS impersonation returns HTTP 200 + real HTML on every Cardrush URL tested. The previous assumption that we needed a real browser was wrong.

Rewriting the scraper solves all three at once.

---

## Goals

- Fetch with **`curl_cffi`**, no browser, no Playwright, no JS runtime.
- Crawl by **rarity bucket** per set, not per card. Typical set finishes in 20–60 s.
- Match listings to catalog by `(set_code, local_id, variant)` so Master Ball Mirror Pikachu is priced separately from normal Pikachu.
- Keep bronze-first ingestion and the existing `insert_price_points` + `ScrapeRun` + `CardScrapeState` contracts.
- Be polite to Cardrush: small page-level sleeps, one active session, respect robots-ish conventions.

---

## Non-goals

- Rewriting SNKRDUNK (separate plan later).
- Changing the database contract for `price_points` (same enums, same idempotent insert).
- Scraping sealed / accessory listings (skipped; `category='card'` only for now).

---

## High-level flow

```
 discover_cardrush (catalog) ──► cards has (set_code, local_id, variant, rarity_code)
                                          │
                                          ▼
 scraper starts for set_code X
   ├─ SELECT DISTINCT rarity_code FROM cards WHERE set_code=X AND is_tracked
   ├─ for each rarity:
   │    ├─ keyword = f"{set_code} {rarity}"  (e.g. "SV2A AR")
   │    ├─ paginate until no new product URLs
   │    ├─ for each listing:
   │    │    ├─ parse name → (local_id, variant, rarity, condition)
   │    │    ├─ lookup card_id in cards (reject unknowns, warn)
   │    │    ├─ build PricePoint row (card_id, condition, price_jpy, stock, external_url, observed_at)
   │    │    └─ accumulate into batch
   │    └─ write bronze object per (set_code, rarity, page)
   ├─ flush batch → insert_price_points(session, rows)
   └─ finish_scrape_run + upsert_card_state per card touched
```

Single `curl_cffi.Session` reused across all requests for the run.

---

## Query strategy

### Cardrush URL form

```
GET https://www.cardrush-pokemon.jp/product-list
    ?keyword={set_code} {rarity}
    &page={n}
```

Empirically:
- `keyword=SV2A AR` returns 105 items across ~2 pages. Clean.
- `keyword=M2A MA` returns ~67 items. Clean.
- Plain `keyword=SV2A` without rarity returns ~1,900 items across 19+ pages (Cardrush also returns M2/M2a contamination on the `m2` substring).

### Pagination stop rule

Paginate until any of:
1. A page returns 0 `.list_item_cell` rows.
2. A page adds **no new product URLs** to a running dedup set (some Cardrush queries keep returning 200 with the last-page contents indefinitely — URL-dedup is the reliable stop).
3. Safety cap: 30 pages per `(set_code, rarity)`.

### Set disambiguation

For each `.list_item_cell`, read `.model_number_value`. If it doesn't equal the expected set code (case-insensitive, handling quirks like `SV2a` vs `SV2A`), skip the row. This is the fix for the `m2` → M2+M2a contamination problem.

### Rarity matching

The product name also carries `【{tag}】`. Keep rows where the tag matches the rarity we asked for. `【-】` rows (variant parallels) are expected whenever the variant's underlying card has rarity `X` but Cardrush elides it — handled at the catalog layer, the scraper ignores them (they're rare as distinct listings and covered under the base card's variant row).

---

## Parser responsibilities

Reuses `packages/catalog/pokeprice_catalog/parser.py` grammar (authoritative). The scraper-side parser additionally extracts:

| Input                                       | Field            | Mapping |
|---------------------------------------------|------------------|---------|
| `〔状態A-〕` prefix                            | condition        | `A-` |
| `〔状態B〕` prefix                             | condition        | `B` |
| `〔状態C〕` prefix                             | condition        | `C` |
| _(no prefix)_                               | condition        | `A` |
| `.selling_price` text `"1,780円(税込)"`      | price_jpy        | `1780` (int) |
| `.stock` text `"在庫数 3点"` / `"在庫数 124枚"` | stock_qty        | `3` / `124` |
| `a.item_data_link[href]`                    | external_url     | as-is (absolute) |

Rows that fail to extract `(local_id/variant)` or whose condition is unrecognized are dropped with a counter bump, not an exception.

---

## Card lookup

```python
async def find_card_id(
    session: AsyncSession,
    *, set_code: str, local_id: str, variant: str
) -> str | None:
    """Lookup card_id in catalog. Returns None on miss (warning logged)."""
```

Misses are bucketed and reported at end-of-run. Expected miss rate: < 1 % (mostly typos, promo oddities, or genuinely new cards the catalog hasn't discovered yet).

When we notice repeated misses for a given `(set_code, local_id, variant)`, the ops response is to run `python -m pokeprice_catalog discover-cardrush --set {set_code}` (idempotent) and re-run the scraper; there is no in-line catalog write from the price scraper.

---

## Package layout (rewritten)

```
packages/scraper_cardrush/
├── pyproject.toml                   # curl_cffi, beautifulsoup4, sqlalchemy[asyncio], pokeprice_core
└── pokeprice_cardrush/
    ├── __init__.py
    ├── __main__.py                  # CLI: --set SV2A | --set M2A | --all
    ├── client.py                    # curl_cffi Session + paginate(set_code, rarity)
    ├── parser.py                    # listing HTML → ListingRow dataclass
    ├── conditions.py                # prefix parser (shared with older code, no change)
    ├── run.py                       # orchestration: ScrapeRun, batches, state
    └── retry.py                     # exponential backoff on 5xx/timeouts
```

Files to delete from the current package: everything tied to Playwright (browser launch, CF wait loop, stealth arguments). The Playwright dependency is removed from `pyproject.toml`.

---

## Operational details

- **Concurrency**: single-threaded per run. One `curl_cffi.Session`, one asyncio worker. Simpler, predictable, polite.
- **Jitter**: `settings.scraper_jitter_min_sec` / `_max_sec` sleep between page fetches (reuse existing config). Default ~0.3–0.8 s.
- **Timeouts**: 15 s per request; 3 retries with exponential backoff on 5xx / read-timeout.
- **Rate profile**: at 0.5 s/page, a full catalog pass (27 sets × ~6 rarities × ~2 pages each) ≈ 5 min.
- **Bronze objects**: one per `(set_code, rarity, page)`, key `bronze/cardrush/dt=YYYY-MM-DD/set={SET}/run={id}/{rarity}-p{n}.html`. This replaces the current per-card key shape.
- **Idempotency**: relies unchanged on `uq_price_points_idem`. Re-running within the same second is a no-op; re-running next hour writes fresh rows as intended.

---

## CLI

```bash
# Single set
uv run python -m pokeprice_cardrush --set SV2A

# Every tracked set in a block
uv run python -m pokeprice_cardrush --era SV
uv run python -m pokeprice_cardrush --era M

# Everything
uv run python -m pokeprice_cardrush --all

# Diagnostics
uv run python -m pokeprice_cardrush --set SV2A --rarity AR --dry-run --limit-pages 2
```

---

## Testing

- **Unit** (`tests/unit/test_cardrush_parser.py`): feed saved HTML fixtures (one normal, one variant, one secret rare, one sealed-skip case, one condition-prefix case). Assert `ListingRow` fields.
- **Unit** (`tests/unit/test_cardrush_pagination.py`): mock client that returns a known sequence of pages; assert stop rule triggers at the first page with no new URLs.
- **Integration (manual)**: `--set SV2A --dry-run` prints expected counts (listings / conditions / variants) without DB writes.
- **Smoke**: full SV2A run against a clean DB, verify `price_points` count by condition and by rarity matches what `--dry-run` said; check bronze objects landed in MinIO.

---

## Performance expectations

| Scope                         | Pages fetched | Wall-clock |
|-------------------------------|---------------|------------|
| One rarity (`SV2A AR`)        | ~2            | ~2 s       |
| One set (`SV2A`, 8 rarities)  | ~16           | ~15 s      |
| Full SV block (25 sets)       | ~400          | ~4 min     |
| Full catalog (SV + M)         | ~450          | ~5 min     |

For comparison the current per-card Playwright scraper takes ~10 min per set.

---

## Acceptance criteria

- `uv sync` no longer installs Playwright in `scraper_cardrush`'s environment.
- `playwright install chromium` is not referenced anywhere in the scraper or docs.
- `--set SV2A` run on a clean DB:
  - completes in < 60 s
  - writes > 1,000 `price_points` rows
  - bronze objects exist under `bronze/cardrush/dt=…/set=SV2A/`
  - `scrape_runs` has a `completed` entry with `cards_succeeded > 0` and `rows_written > 0`
  - no `card_id` lookup miss beyond 1 % of listings
- `--set M2A` run:
  - prices `MA`-rarity cards (catalog must already have them from `discover-cardrush`)
  - prices at least one variant (e.g. `(マスターボールミラー)` → `variant='master_ball_mirror'`) with a non-empty `price_points` row
- Second invocation of `--set SV2A` (within the hour) is idempotent (no duplicate rows under `uq_price_points_idem`).
- All unit tests pass; ruff + mypy clean.

---

## Rollout steps

1. Finish `catalog-metadata.md` implementation (catalog is a hard dep).
2. Create `packages/scraper_cardrush` v2 on a branch, gated.
3. Run new scraper against staging DB, diff results against historical Playwright-era SV2A run.
4. Point scheduler (`packages/scheduler`) at new package.
5. Delete old Playwright code and its dependency.

---

## Research notes (reference)

### curl_cffi posture (measured 2026-04-21)

- `impersonate='chrome120'` → HTTP 200, 390 KB, no challenge.
- Works across `chrome120|chrome124|chrome131|safari17_0`.
- Tried plain `httpx` / `curl` → HTTP 403 + `cf-mitigated: challenge` (TLS-level block).

### Cardrush name grammar (measured)

```
[〔状態{A-|B|C}〕] {card_name_ja}[(variant_jp)] 【{rarity_tag}】 {{local_id/total}}
```

See `catalog-metadata.md` for the canonical grammar table.

### Rarity distributions (measured per set)

| Set  | Rarities                                     |
|------|----------------------------------------------|
| SV2A | C=643, U=645, R=249, RR=67, AR=115, SR=94, SAR=50, UR=12 |
| M1S  | C=785, U=581, R=194, RR=148, AR=463, SR=382, SAR=176, MUR=30 |
| M3   | C=976, U=635, R=225, RR=177, AR=244, SR=395, SAR=100, MUR=29 |
| M2   | … RR=200, AR=374, SR=298, SAR=199, MUR=31, MA=(shared with M2A namespace in `m2` keyword) |
| M2A  | RR=265, AR=76, SR=30, SAR=61, MUR=4, **MA=67** |

Variant `【-】` rows are 30–80× more common than non-variant listings in MEGA-era sets (m2a: 3,315 variant rows vs ~500 rarity-tagged rows on a single page).

### Cloudflare fallback plan

If Cardrush ever escalates beyond TLS fingerprinting (e.g., adds a Turnstile widget):
- Primary fallback: **Camoufox** (stealth-patched Firefox, drop-in for Playwright). Works against Turnstile.
- Not `playwright-stealth`: its JS-level patches are routinely caught by Cloudflare's 2026 detection.

No code is written for this fallback until / unless needed.
