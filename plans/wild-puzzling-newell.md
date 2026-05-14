# Plan: TCGCollector Audit + Promo Card Support

## Context

The catalog covers 98 JP sets. Three problems exist:

1. **Missing high-value sets** — Pokémon Card Classic (CLF/CLL/CLK, Oct 2023) and other sets
   visible on TCGCollector's sets page as >$100 USD are not in the catalog at all.
2. **Four promo series uncatalogued** — M-P (Mega/XY era, ~195 cards), SM-P (Sun & Moon,
   400+ cards), S-P (Sword & Shield, ~300 cards), SV-P (Scarlet & Violet, 200+ ongoing) have
   never been bootstrapped. These contain some of the most valuable JP cards (PSA10 SM-P
   promos regularly exceed $500).
3. **TCGCollector audit not rolled out** for all high-value existing sets — rarity/illustrator
   gaps remain where Pokellector labels are coarse ("Secret Rare").

Internal set codes must be **hyphen-free** because `parse_artwork_id`/`parse_card_id` splits
on `-` and assumes exactly 3/4 segments (CLAUDE.md §6.3 invariant).

---

## Part A — Discover and Add Missing High-Value Sets

### A1. Identify missing sets via TCGCollector sets page

During implementation, fetch `https://www.tcgcollector.com/sets/jp` using `curl_cffi`
(already available in `tcgcollector_client.py`). Find all sets with USD value >$100.
Cross-reference against our 98 sets to find gaps.

**Already confirmed missing (from user):**

| set_code | Name EN | era_block | Cards | Notes |
|----------|---------|-----------|-------|-------|
| `CLF` | Pokémon Card Classic (Venusaur) | `cl` | 34 | Released Oct 31, 2023 |
| `CLL` | Pokémon Card Classic (Charizard) | `cl` | 34 | Same release |
| `CLK` | Pokémon Card Classic (Blastoise) | `cl` | 34 | Same release |
| `svG` | Unknown SV-era set | TBD | TBD | Confirm identity during impl |

Use a new `era_block: cl` for the Classic collection — they are a premium standalone product
released during SV era but distinct from the SV expansion line. Adding them to `sv` would
route them into the daily SV Cardrush job, which is wrong (they have fixed inventory, not
ongoing listings).

### A2. Create set YAML files for missing sets

File pattern: `data/sets/<CODE>.yml`. During implementation, find `pokellector_slug`,
`tcgcollector_id`, `tcgcollector_slug`, and `tcgdex_id` by browsing Pokellector and
TCGCollector for these sets.

Example structure for CLF:
```yaml
set_code: CLF
era_block: cl
language: jp
name_ja: ポケモンカードゲームクラシック（フシギバナ）
name_en: Pokémon Card Classic (Venusaur)
release_date: 2023-10-31
total: 34
tcgdex_id: # confirm
pokellector_slug: # confirm
tcgcollector_id: # confirm
tcgcollector_slug: # confirm
```

Same structure for CLL (Charizard), CLK (Blastoise), and any additional sets found in A1.

### A3. Bootstrap + seed

```bash
make catalog-bootstrap SET=CLF   # Pokellector + TCGdex + Cardrush → data/cards/CLF/*.yml
make catalog-bootstrap SET=CLL
make catalog-bootstrap SET=CLK
make catalog-seed-sets           # upsert new sets into DB
make catalog-seed-cards          # upsert artworks + cards
make catalog-verify              # confirm 0 orphans, 0 null rarity_code
```

Classic sets behave exactly like normal sets — standard rarity-bucket bootstrap applies.

---

## Part B — TCGCollector Audit Rollout for High-Value Existing Sets

### B1. Identify qualifying sets

Query from DB: any set where `total_value_jpy > 14620` (≈ $100 USD at 0.0065 rate).
All 98 sets already have audit YMLs fetched (Phase 2 complete). This is purely Phase 3+5
(diff → auto-apply → reseed).

Likely candidates (SV+ME fully scraped): SV2A, M2A, SV8A, M1L, M2, SV4A, M4, M3, M1S, etc.
Also include all newly added sets from Part A.

### B2. Run audit rollout

```bash
make catalog-audit-rollout SET=SV2A   # fetch → diff → auto-apply → reseed
make catalog-audit-rollout SET=M2A
make catalog-audit-rollout SET=CLF    # new set — fetches TCGCollector for first time
# ... repeat for every qualifying set
```

Rollout is idempotent. Already-applied sets will produce no-op diffs.

---

## Part C — Add Four Promo Series to Catalog

### C1. Internal set_code mapping

| Official notation | Internal `set_code` | `era_block` | Approx cards |
|---|---|---|---|
| M-P (Mega/XY era promos) | `MP` | `me` | ~195 |
| SM-P (Sun & Moon era promos) | `SMPR` | `sm` | 400+ |
| S-P (Sword & Shield era promos) | `SP` | `sw` | ~300 |
| SV-P (Scarlet & Violet era promos, ongoing) | `SVP` | `sv` | 200+ |

`SMP` is taken (collides with `SMP2`), so SM-P becomes `SMPR`.

Resulting artwork IDs (all valid, no hyphens in set_code part):
- `jp-mp-020` (020/M-P Pikachu McDonald)
- `jp-smpr-297` (297/SM-P Eevee+Snorlax)
- `jp-smpr-001` (001/SM-P Snorlax)

### C2. Create promo set YAML files

Same structure as A2. Find slugs from Pokellector (JP promo series pages) and TCGCollector
during implementation. Example for SMPR:

```yaml
set_code: SMPR
era_block: sm
language: jp
name_ja: SM-P プロモーションカード
name_en: SM-P Promotional Cards
release_date: 2016-11-18
total: null   # promo series are open-ended; leave null
tcgdex_id: # confirm (likely "smp")
pokellector_slug: # confirm
tcgcollector_id: # confirm
tcgcollector_slug: # confirm
```

Files: `data/sets/MP.yml`, `data/sets/SMPR.yml`, `data/sets/SP.yml`, `data/sets/SVP.yml`

### C3. Update `_STRICT_EXEMPT_SETS` in `verify.py`

Promo sets have large name_ja gaps — upstream sources (Pokellector, TCGdex) have incomplete
Japanese names for rare promo cards. Add all four codes to the exempt list:

File: `packages/catalog/watari_catalog/verify.py`

```python
_STRICT_EXEMPT_SETS: frozenset[str] = frozenset({
    "SMP2",
    "SM0",
    "MP",    # ← add
    "SMPR",  # ← add
    "SP",    # ← add
    "SVP",   # ← add
})
```

### C4. Bootstrap + seed + audit

```bash
make catalog-bootstrap SET=MP
make catalog-bootstrap SET=SMPR
make catalog-bootstrap SET=SP
make catalog-bootstrap SET=SVP
make catalog-seed-sets && make catalog-seed-cards
make catalog-verify
make catalog-audit-rollout SET=MP
make catalog-audit-rollout SET=SMPR
make catalog-audit-rollout SET=SP
make catalog-audit-rollout SET=SVP
```

---

## Part D — Cardrush Promo Scraping

### Problem

Current scraper searches `keyword="{set_code} {rarity_bucket}"` (e.g. `"sv2a sr"`).
Promo cards have no rarity buckets. Cardrush product names for promos include the series
suffix: `"020/M-P ピカチュウ"`, `"297/SM-P イーブイ&カビゴン"`.

The existing `_SET_LOCAL_RE` regex expects a set-code token BEFORE the local ID. Promo
format has the promo series AFTER the local ID. It would parse `set_code=None`.

### D1. New promo regex in `packages/scraper_cardrush/watari_cardrush/parser.py`

Add `_PROMO_LOCAL_RE` and `_PROMO_SERIES_TO_SET_CODE` alongside existing constants:

```python
# Promo format: "020/M-P", "297/SM-P", "001/S-P", "001/SV-P"
_PROMO_LOCAL_RE = re.compile(
    r"(?P<local>\d{1,4})/(?P<series>SV-P|SM-P|S-P|M-P)"
)

_PROMO_SERIES_TO_SET_CODE: dict[str, str] = {
    "M-P":  "mp",
    "SM-P": "smpr",
    "S-P":  "sp",
    "SV-P": "svp",
}
```

At the top of `parse_cardrush_product_name` (BEFORE the existing `_SET_LOCAL_RE` check),
add a promo branch:

```python
if m := _PROMO_LOCAL_RE.search(name):
    set_code = _PROMO_SERIES_TO_SET_CODE[m.group("series")]
    local_id = m.group("local")
    # ... continue with same rarity/variant/name_ja extraction
```

**Critical ordering:** Promo check must come first. A string like `"297/SM-P イーブイ"`
would have `_SET_LOCAL_RE` produce `set_code=None` if checked first; promo check produces
the correct `set_code="smpr"`.

### D2. New promo search mode in `packages/scraper_cardrush/watari_cardrush/run.py`

Add keyword map near `_CARDRUSH_BASE_ALIAS`:

```python
_CARDRUSH_PROMO_KEYWORD: dict[str, str] = {
    "MP":   "M-P",
    "SMPR": "SM-P",
    "SP":   "S-P",
    "SVP":  "SV-P",
}
```

Add `_crawl_promo(*, set_code, promo_keyword, ...)` private function — identical to
`_crawl_rarity` but:
- Search keyword is `promo_keyword` (e.g. `"SM-P"`) with no set code prefix or rarity suffix
- Bronze key suffix: `f"promo-p{page_num}.html"` (instead of `f"{rarity_code}-p{page_num}.html"`)
- No rarity-bucket loop needed — single paginated search

Add `scrape_promo_set(set_code, *, max_pages=50, dry_run=False)` public function:
- Validates set_code is in `_CARDRUSH_PROMO_KEYWORD`
- Calls `_crawl_promo` once (no rarity-bucket loop)
- Calls existing `upsert_price_points`, `upsert_graded_price_points`, `finish_scrape_run`,
  and `refresh_price_mvs_if_needed` — identical to `scrape_set`

Update the CLI dispatcher in `__main__.py` to auto-route promo sets:

```python
promo_codes = [c for c in set_codes if c.upper() in _CARDRUSH_PROMO_KEYWORD]
normal_codes = [c for c in set_codes if c.upper() not in _CARDRUSH_PROMO_KEYWORD]
# Call scrape_promo_set for promos, scrape_set for normals
```

This means `make scrape-cardrush SET=MP` works without a new Makefile target.

**During implementation:** Probe Cardrush with `keyword="M-P"` and `keyword="SM-P"` to
verify these search terms return listings in the expected `"020/M-P"` format before
committing.

---

## Part E — SNKRDUNK Promo Product Numbers

### Problem

SNKRDUNK constructs `product_number = f"pkmn-tcg-{era}-{local_id}"` where `era` comes from
`set_code.lower()`. Internal set_code `SMPR` → era `smpr` → `pkmn-tcg-smpr-297`. But
SNKRDUNK almost certainly uses `sm-p` (the official notation with hyphen in the era part),
yielding `pkmn-tcg-sm-p-297`.

Note: the product number era CAN contain hyphens; only our internal `set_code` must not.

### E1. Probe before implementing

Run against known examples (020/M-P, 297/SM-P, 001/SM-P from user):

```python
# Quick probe script (run interactively):
from watari_snkrdunk.client import SnkrdunkClient
import asyncio

async def probe():
    async with SnkrdunkClient() as c:
        for era, local_id in [("m-p", "020"), ("sm-p", "297"), ("sm-p", "001"),
                               ("s-p", "001"), ("sv-p", "001")]:
            r = await c.resolve_apparel(era, local_id)
            print(f"{era} / {local_id}: {r}")

asyncio.run(probe())
```

### E2. Add era slug override map in `packages/scraper_snkrdunk/watari_snkrdunk/run.py`

After probing, populate and add near top of file:

```python
# SNKRDUNK product-number era slugs for sets whose internal set_code
# does not match SNKRDUNK's namespace. Populated after manual probe.
_SNKRDUNK_ERA_SLUG_OVERRIDE: dict[str, str] = {
    "MP":   "m-p",   # confirm: pkmn-tcg-m-p-020
    "SMPR": "sm-p",  # confirm: pkmn-tcg-sm-p-297
    "SP":   "s-p",   # confirm: pkmn-tcg-s-p-001
    "SVP":  "sv-p",  # confirm: pkmn-tcg-sv-p-001
}
```

In `scrape_era`, resolve the slug before constructing product numbers:

```python
era_slug = _SNKRDUNK_ERA_SLUG_OVERRIDE.get(era.upper(), era.lower())
# use era_slug when calling resolve_apparel(era_slug, local_id)
```

No new `scrape_promo_era` function — existing `scrape_era` handles it via the override.

---

## Part F — CI Schedule (`scrape.yml`)

File: `.github/workflows/scrape.yml`

**Classic sets (CLF/CLL/CLK):** behave like normal sets.
- Cardrush: add `cardrush-cl` job on the existing `0 0,8 * * *` daily schedule
- SNKRDUNK: add `clf`, `cll`, `clk` to the existing daily SNKRDUNK era matrix

**Promo sets (MP/SMPR/SP/SVP):** slow-changing inventory → weekly is sufficient.
- Cardrush: add `cardrush-promos` job on the Saturday `0 21 * * 0` schedule (same as
  `cardrush-sw` and `cardrush-sm`); matrix over `[MP, SMPR, SP, SVP]` — CLI auto-routes
  to `scrape_promo_set` since all four are in `_CARDRUSH_PROMO_KEYWORD`
- SNKRDUNK: add promo eras to the existing `snkrdunk-legacy` weekly matrix, using the
  internal codes (`smpr`, `mp`, etc.) which the override map will translate

---

## Files Modified / Created

| File | Change |
|------|--------|
| `data/sets/CLF.yml`, `CLL.yml`, `CLK.yml` | New — Classic collection (3 sets) |
| `data/sets/MP.yml`, `SMPR.yml`, `SP.yml`, `SVP.yml` | New — promo series (4 sets) |
| `data/cards/CLF/`, `CLL/`, `CLK/` | Generated by `catalog-bootstrap` |
| `data/cards/MP/`, `SMPR/`, `SP/`, `SVP/` | Generated by `catalog-bootstrap` |
| `packages/catalog/watari_catalog/verify.py` | Add 4 promo codes to `_STRICT_EXEMPT_SETS` |
| `packages/scraper_cardrush/watari_cardrush/parser.py` | `_PROMO_LOCAL_RE`, `_PROMO_SERIES_TO_SET_CODE`, promo branch in `parse_cardrush_product_name` |
| `packages/scraper_cardrush/watari_cardrush/run.py` | `_CARDRUSH_PROMO_KEYWORD`, `_crawl_promo`, `scrape_promo_set` |
| `packages/scraper_cardrush/watari_cardrush/__main__.py` | Auto-route promo set_codes to `scrape_promo_set` |
| `packages/scraper_snkrdunk/watari_snkrdunk/run.py` | `_SNKRDUNK_ERA_SLUG_OVERRIDE`, era slug override in `scrape_era` |
| `.github/workflows/scrape.yml` | `cardrush-cl` (daily), `cardrush-promos` (weekly), promo + CL in SNKRDUNK matrices |

---

## Implementation Order

1. Research slugs: visit Pokellector + TCGCollector for CLF/CLL/CLK/MP/SMPR/SP/SVP
2. Create 7 set YAML files in `data/sets/`
3. Update `verify.py` `_STRICT_EXEMPT_SETS`
4. Add `_PROMO_LOCAL_RE` + promo branch to Cardrush `parser.py`
5. Add `_CARDRUSH_PROMO_KEYWORD` + `scrape_promo_set` to Cardrush `run.py`
6. Update `__main__.py` dispatcher
7. Probe SNKRDUNK for promo era slugs (interactive script)
8. Add `_SNKRDUNK_ERA_SLUG_OVERRIDE` + era slug override to SNKRDUNK `run.py`
9. Bootstrap all 7 new sets + seed DB
10. Run TCGCollector audit rollout for all high-value sets (Part B)
11. Update CI `scrape.yml`
12. Write new unit tests

---

## New Unit Tests

File: `tests/unit/test_cardrush_parser.py` — add `TestPromoProductName`:
```python
# parse_cardrush_product_name("297/SM-P イーブイ&カビゴン") → set_code="smpr", local_id="297"
# parse_cardrush_product_name("020/M-P ピカチュウ")         → set_code="mp",   local_id="020"
# parse_cardrush_product_name("001/SV-P カイリュー")         → set_code="svp",  local_id="001"
# parse_cardrush_product_name("001/S-P リザードン")          → set_code="sp",   local_id="001"
# parse_cardrush_product_name("sv2a 163/165 ミュウツー ex")  → set_code="sv2a", local_id="163"
#   (normal format must still work; "163/165" must NOT match promo regex)
```

File: `tests/unit/test_cardrush_run.py` — add `TestCardrushPromoKeywordMap`:
```python
# _CARDRUSH_PROMO_KEYWORD["MP"] == "M-P"
# _CARDRUSH_PROMO_KEYWORD["SMPR"] == "SM-P"
# "SV2A" not in _CARDRUSH_PROMO_KEYWORD  (normal sets excluded)
# "CLF" not in _CARDRUSH_PROMO_KEYWORD   (Classic sets excluded)
```

Expected test count after implementation: 376 existing + ~10 new = ~386.

---

## Verification Checklist

1. `data/sets/` has 7 new YML files; `make catalog-seed-sets` seeds 106 sets total
2. `make catalog-bootstrap SET=SMPR` generates ~400+ card YMLs; no errors
3. `make catalog-seed-cards` inserts artworks + cards for all new sets
4. `make catalog-verify` — 0 orphans, 0 null rarity_code (promo sets exempt from strict)
5. `GET /jp/sets/SMPR/cards` returns card list
6. `GET /jp/sets/CLF/cards` returns 34 cards
7. Cardrush probe: `keyword="SM-P"` search returns listings with `"297/SM-P"` format
8. After `make scrape-cardrush SET=MP`: `price_points` has rows for `set_code='MP'`
9. After `make scrape-snkrdunk ERA=smpr`: `price_points` has rows for `jp-smpr-*` card IDs
10. Card `jp-smpr-297-normal` appears in `graded_price_points` (PSA10 graded sales exist)
11. `make catalog-audit-rollout SET=CLF` runs without error; improves rarity coverage
12. `make test` passes 386+ tests
13. CLAUDE.md updated: §4.1 smoke results, §5 roadmap updated, §6 new gotchas if any
