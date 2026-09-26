# Cardmarket EU price for JP cards — design

- **Date:** 2026-09-26
- **Status:** approved design, not yet implemented
- **Goal:** give every JP card a dedicated, native-EUR Cardmarket price so an
  EU-based seller can rank which cards are worth listing on Cardmarket.

## 1. Background & findings

### 1.1 Current implementation

- `PriceProxy.tcgdex_international` (`packages/api/watari_api/price_proxy.py`)
  fetches TCGdex **JP locale** `/v2/ja/cards/{tcgdex_id}-{local_id}` per card
  (live, 30-min cache) and reads `pricing.cardmarket`.
- Only `avg`, `trend`, `low` are used. Each becomes an `InternationalPrice` row
  converted to JPY and returned by `GET /{lang}/cards/{set}/{id}/international-prices`.
- `idProduct`, `avg1/avg7/avg30` and the `*-holo` fields are ignored. The card
  variant is ignored (every print gets the same numbers).
- The `tcgplayer` branch in `tcgdex_international` is dead code: TCGdex JP
  always returns `tcgplayer: null`.
- `CLAUDE.md` invariant #39 and the `fetch_tcgdex_prices` docstring still
  describe the removed EN-locale / pokemontcg.io design (commit `d7aed5c2`).

### 1.2 What the data source actually is

TCGdex's `pricing.cardmarket` block is a verbatim copy of Cardmarket's **public
daily price guide**:

- `https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json`
  (Pokémon = game 6; ~15 MB; ~79k products; fields: `idProduct, idCategory,
  avg, low, trend, avg1, avg7, avg30, avg-holo, low-holo, trend-holo,
  avg1-holo, avg7-holo, avg30-holo`).
- `https://downloads.s3.cardmarket.com/productCatalog/productList/products_singles_6.json`
  (~74k singles; `idProduct, name, idCategory, categoryName, idExpansion,
  idMetacard, dateAdded`; no collector number, no URL slug).

Verified on 2026-09-26 for SV2A (Cardmarket `idExpansion` 5328):

- One Cardmarket product per artwork (210 products = our 210 SV2A artworks).
  Products are the JP printing (Mew ex SAR `719658`, added 2023-06-20, before
  the EN 151 release).
- Product names are **not unique** (Mew ex has 4 products at €1 / €18 / €42 /
  €255), so name matching is unusable; the mapping must come from TCGdex's
  `idProduct`.
- Poké Ball / Master Ball mirrors are **not** separate products; both fall
  into the `*-holo` fields and cannot be told apart.
- TCGdex JP returns `idProduct` for every era sampled (SM1M, SM12a, S8b,
  S12a, SV1S, M2a, M3). All 107 set YAMLs have a `tcgdex_id`.
- TCGdex GraphQL does not expose `pricing`, so the mapping needs one REST call
  per card.

### 1.3 Near Mint filtering — not possible with free data

The price guide has **no condition or language breakdown**. `low` is the
cheapest listing in *any* condition and language (Mew ex SAR: `low €100` vs
`avg €255`; Muk: `low €0.02`), so it is misleading as a price floor.

Sources that do support `minCondition`:

| Route | NM filter | Status |
|---|---|---|
| Product page `?language=7&minCondition=2` (JP, NM or better) | yes | Cloudflare JS challenge: `curl_cffi` chrome + safari impersonation both return 403. Needs a real browser; likely against Cardmarket ToS. |
| Official API `GET /articles/{idProduct}?idLanguage=7&minCondition=NM` | yes | Cardmarket is not accepting new API applications. |
| Paid third-party scrapers (cardmarketapi.com, Apify actors) | yes | Paid, unofficial dependency. |

**Decision:** ship EU prices from the free price guide now; add a real NM
floor in a later pass as an extra field on `EuPrice`.

## 2. Decisions

| Question | Decision |
|---|---|
| NM source | Price guide now, NM floor later |
| "Profitable" means | EU value only — no JP-cost comparison, no fee math |
| Surfaces | Card detail + set gallery + `/cards` search, with sort by EU price |
| Architecture | Committed `idProduct` mapping files + price guide held in API memory |
| Display currency | EU prices always native €; also add € to the currency toggle |

## 3. Design

### 3.1 Mapping data — `packages/catalog/data/cardmarket/{SET}.yml`

Generated, never hand-edited (same rule as `data/audit/`). Written with PyYAML
(like other generated audit files).

```yaml
set_code: SV2A
source: tcgdex            # idProduct taken from TCGdex JP pricing.cardmarket
tcgdex_id: SV2a
fetched_at: '2026-09-26T10:00:00+00:00'
totals: { artworks: 210, mapped: 210 }
products:                 # local_id → Cardmarket idProduct, sorted by local_id
  '089': 719531
  '205': 719658
```

Cards with no Cardmarket product are omitted from `products` (visible via
`totals.mapped < totals.artworks`).

### 3.2 Backfill command — `cardmarket-map`

- CLI: `uv run python -m watari_catalog cardmarket-map [--set SV2A] [--refresh]`
  (no `--set` → every set). Makefile: `make catalog-cardmarket-map [SET=SV2A]`.
- Reuses `TcgdexClient(language="ja")`, ~5 concurrent requests.
- Default: fetch only `local_id`s missing from the existing file (Cardmarket
  product IDs are stable, so reruns are cheap and new cards fill in).
  `--refresh`: re-fetch everything.
- Validates each `idProduct` against `products_singles_6.json`
  (`categoryName == "Pokémon Single"`); unknown IDs are dropped and logged.
- Rewrites the file only when content changed.
- First full backfill: ~12k TCGdex calls, roughly 20–40 minutes.

### 3.3 API — `watari_api/cardmarket_guide.py` → `CardmarketGuide`

Sibling of `MemCatalog`, stored on `app.state.cardmarket_guide`, exposed via
`get_cardmarket_guide` in `deps.py`.

- **Startup:** load all `data/cardmarket/*.yml` into
  `(set_code, local_id) → idProduct` (via `asyncio.to_thread`, like
  `MemCatalog.load`).
- **Background refresh task** (started in `lifespan`, cancelled on shutdown):
  download `price_guide_6.json` with `httpx`, keep only mapped `idProduct`s,
  build a new dict, swap atomically. Record the file's `createdAt` as
  `guide_date`. Repeat every 6 h. Startup does **not** wait for the first
  download.
- **Failure handling:** a failed refresh keeps the last good data and retries
  after 15 min. Before the first successful download, all lookups return
  `None`. A set with no mapping file returns `None`.
- **Lookup:** `lookup(set_code, local_id, variant) -> EuPrice | None`.
  - `variant == "normal"` → base fields, `basis="normal"`.
  - every non-`normal` variant (in practice the Poké Ball / Master Ball
    mirrors) → `*-holo` fields, `basis="mirror"`.
  - `0` and `null` both mean "no value".
  - Returns `None` when all of trend/avg30/avg7 are missing for the chosen basis.

### 3.4 Schema — `EuPrice` (`watari_api/schemas.py`)

```python
class EuPrice(BaseModel):
    """Cardmarket price-guide values for one JP card, in native EUR."""

    id_product: int
    url: str                  # Cardmarket product page, pre-filtered ?language=7&minCondition=2
    price_eur: float          # headline/sort value: trend → avg30 → avg7 (never None; see §3.3)
    trend_eur: float | None
    avg7_eur: float | None
    avg30_eur: float | None
    basis: Literal["normal", "mirror"]
    guide_date: datetime
```

`low` is deliberately not exposed (any condition/language → misleading).

### 3.5 Endpoints

- `ArtworkSearchResult` gains `eu_price: EuPrice | None` (normal-variant
  basis). Populated in `/cards/search` and `/cards/by-sets` from the in-memory
  guide — no extra I/O.
- New `GET /{lang}/cards/{set_code}/{local_id}/eu-price?variant=normal` →
  `EuPrice`, or 404 when unmapped / no price. Same `Cache-Control` as the other
  price endpoints. Sits under the existing `/{lang}` router (rate limit + locale
  validation inherited; no per-router `rate_limit_dep`).
- `/international-prices` drops the Cardmarket rows and becomes
  PriceCharting-only. Remove `tcgdex_international`, `fetch_tcgdex_prices`,
  `_do_fetch_tcgdex`, the TCGdex cache/locks in `PriceProxy`, and the dead
  TCGPlayer branch. (`_parse_tcgdex_date` goes too if nothing else uses it.)

### 3.6 Product link

`url` opens the Cardmarket product filtered to Japanese, Near Mint or better
(`?language=7&minCondition=2`), so the real NM floor is one click away until
the NM field ships.

Verified 2026-09-26 in a browser: `https://www.cardmarket.com/en/Pokemon/Products?idProduct={id}` resolves to the product page.

### 3.7 Frontend (`apps/web`)

- **Types / hooks:** `EuPrice` in `types/api.ts`; `eu_price` on
  `ArtworkSearchResult`; `useEuPrice(setCode, localId, variant)` in
  `api/prices.ts`.
- **Card detail:** new `components/prices/EuPriceCard.tsx` at the top of the
  price section, driven by the variant switcher:

  ```
  ┌ Cardmarket (EU) ──────────────────────────────┐
  │ €237.66  trend                                │
  │ 7-day avg €260.84 · 30-day avg €252.72        │
  │ Basis: Normal            Guide: 25 Sep 2026   │
  │ [View JP Near Mint listings on Cardmarket ↗]  │
  └───────────────────────────────────────────────┘
  ```

  Mirror variants show "Basis: Mirror (Poké Ball + Master Ball combined)".
  Hidden on 404. `InternationalPriceTable` loses its Cardmarket group
  automatically.
- **Thumbnails** (`CardThumbnail` / `SearchCardThumbnail`): second line
  `EU €12.40` from the embedded `eu_price`; omitted when `null`. No extra
  requests.
- **Sort:** new `SortKey`s `eu_price_desc` / `eu_price_asc` in
  `CardFilterBar`, the `/cards` search dropdown, and `sortSearchCards`
  (cards without an EU price sort last in both directions). On `/cards`
  search the sort covers the fetched batch only — same limitation as the
  existing JP price sort.
- **Currency:** EU prices always render in native € via a small
  `formatEUR` helper, regardless of the toggle. Also add EUR to the currency
  toggle: `Currency = "JPY" | "USD" | "VND" | "EUR"`, Frankfurter
  `to=USD,VND,EUR`, a fallback EUR rate, a € button in `CurrencyToggle`, and
  `"EUR"` accepted by `readStoredCurrency`.

## 4. Testing

The web app has no test runner; frontend is verified with `make web-build`
(type check) plus a manual pass in the browser.

- `tests/unit/test_cardmarket_guide.py`
  - loads a small price-guide fixture and keeps only mapped products
  - `normal` → base fields; mirror variants → `*-holo`, `basis="mirror"`
  - headline fallback trend → avg30 → avg7; `0` treated as missing
  - failed refresh keeps last good data
  - unmapped card / missing mapping file → `None`
- `tests/unit/test_cardmarket_map.py` (fake `TcgdexClient`)
  - fills only missing IDs; `--refresh` re-fetches all
  - IDs absent from the product catalog are dropped
  - YAML output is deterministic (sorted keys, stable totals)
- `tests/unit/test_api.py`
  - `FakeCardmarketGuide` injected via `dependency_overrides`
  - `/eu-price` 200 + 404; mirror variant returns `basis="mirror"`
  - `/cards/search` and `/cards/by-sets` results include `eu_price`
  - `/international-prices` returns no `market == "cardmarket"` rows
  - update `FakePriceProxy` for the removed TCGdex methods

## 5. Docs

- `CLAUDE.md`
  - §3.5: add `/eu-price` to the route table; note `eu_price` on search results.
  - Replace stale invariant #39 with a Cardmarket invariant: mapping files are
    generated (never hand-edit; rerun `cardmarket-map`); `low` is deliberately
    not exposed; mirrors share the `*-holo` row; mapping comes from TCGdex
    `idProduct`, never name matching.
  - Invariant #24: documented exception for native-EUR `EuPrice` fields.
  - §3.7: currency toggle now ¥/$/₫/€.
  - §7: `make catalog-cardmarket-map [SET=...]`.
- Update the project memory file accordingly.

## 6. Rollout

1. Verify the product-link URL form in a real browser (§3.6).
2. Run the full backfill locally; commit `packages/catalog/data/cardmarket/*.yml`.
3. Deploy. No DB changes, no migration.
4. For each future new set: `make catalog-cardmarket-map SET=<code>` after
   bootstrap, commit, redeploy.

## 7. Out of scope (this pass)

- Near Mint floor (next pass; new field on `EuPrice`; source still to be chosen).
- Separate Poké Ball vs Master Ball mirror prices.
- Fees, shipping, and profit/arbitrage math.
- Server-side sorting for cross-set `/cards` search.

## Amendments (found during implementation)

1. **FX rates were already broken at design time.** `api.frankfurter.app`
   301-redirects to `api.frankfurter.dev/v1/latest`; httpx doesn't follow
   redirects by default, so `/rates` and the old FX fetch always failed.
   Frankfurter also has no VND. Fixed by pointing at the new host with
   `follow_redirects=True`; `/rates` returns `{USD, EUR}` only and the
   frontend fills `VND` from its own fallback constant.
2. **15 set YAMLs have an empty `tcgdex_id`** (all ME sets, CL, promos) —
   not a blocker. TCGdex JP ids are case-insensitive and match `set_code`
   directly (e.g. ME sets resolve as `M2A → M2a`), with `SVP → SV-P` /
   `MP → M-P` overrides. CL, SMPR, SP simply aren't on TCGdex.
3. **Product-id validation** uses every `idProduct` in
   `products_singles_6.json` (the file only contains category 51 "Pokémon
   Single").
4. **Link form verified:** `Products?idProduct=` resolves — §3.6's open item
   is closed above.
5. **`resolve_tcgdex_id(set_code)` never reads the YAML `tcgdex_id` field at
   all**, not just for the 15 empty ones. Several non-empty YAML values
   aren't TCGdex JP ids either (`sv01` for SV1S, `sv01v` for SV1V, `sv01a`
   for SV1A, `SM1+`…`SM5+` for SM1P–SM5P), so the map command always derives
   the TCGdex id from `set_code` instead. Those YAML `tcgdex_id` values
   remain in use by `_populate_official_totals` (§3.7 of `CLAUDE.md`), so
   SV1S/SV1V/SV1A/SM1P–SM5P may lack an official set total — a known,
   separate issue, not fixed here.
6. **Ambiguous idProduct guard added.** `CardmarketGuide.load_mappings`
   drops every card whose idProduct is claimed by more than one card (a
   TCGdex data error — Cardmarket has one product per artwork) and logs a
   warning. The full backfill (2026-09-26) drops 7 cards: SV9A
   002/022/039/064/071/074 and SVP 262.
