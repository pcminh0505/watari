# Plan — Catalog (metadata layer)

**Status**: draft, awaiting approval before implementation
**Scope**: Wipe and rebuild the catalog schema + bootstrap pipeline. Price scrapers are out of scope (see `cardrush-scraper-rewrite.md` and future SNKRDUNK plan).
**Supersedes**: `iterative-zooming-walrus.md` (M1 catalog section).

---

## Mental model

```
┌─────────────────────────────────────────────────────────┐
│  Catalog (this plan)                                    │
│  ───────────────────                                    │
│  Pure metadata. Answers "what cards exist?"             │
│     sets + cards tables                                 │
│     fields: name_ja, name_en, image, rarity, variant,   │
│             illustrator, regulation_mark, ...           │
│     no prices, no scrape state.                         │
└──────────────────────┬──────────────────────────────────┘
                       │ (card_id, variant)
                       ▼
┌─────────────────────────────────────────────────────────┐
│  Price discovery services (separate plans)              │
│  ─────────────────────────────────────────             │
│   • cardrush  (listing prices)                          │
│   • snkrdunk  (last-sold prices)                        │
│   • tcgdex    (optional, EN/market reference)           │
│                                                         │
│  Each one reads cards (+ tier/is_tracked) and appends   │
│  rows to price_points.                                  │
└─────────────────────────────────────────────────────────┘
```

Keep it simple. The catalog is **one table of sets + one table of cards**. Everything else (price points, scrape state, scrape runs) is downstream.

---

## Design principles

1. **Simple schema, few columns.** If a field isn't actively used for search, filtering, or display, push it into `source_refs` JSONB instead of a dedicated column.
2. **Variant is a first-class column.** Parallel printings (Master Ball Mirror, Dark Ball Mirror, etc.) must not collapse into one `card_id`.
3. **Multi-source catalog, explicit precedence.** Each field has a well-known preferred source:
   - `name_en`, `image_url` → **TCGdex** (cleanest EN/image data).
   - Set and card existence, `name_ja`, `rarity_code`, `variant` → **Cardrush** (100% current market coverage, incl. sets TCGdex is late on like M2 / M2a).
   - `set_code`, `era_block`, `parent_set_code`, `tcgdex_id` → **`sets.yml`** (human-owned source of truth).
   - `release_date`, `total` → **discovery-filled** (TCGdex if present, else inferred from Cardrush max local_id).
4. **Idempotent builds.** `seed-sets`, `enrich-tcgdex`, `discover-cardrush` can each be run repeatedly and reach the same state. All writes are upserts keyed by `(set_code, local_id, variant)`.
5. **Wipe-and-rebuild is allowed on this migration.** We accept dropping the existing 3,341 rows and the sv2a price points. Future catalog changes should be additive migrations.

---

## Schema

```sql
-- =========================================================
-- sets: one row per printed expansion / set
-- =========================================================
CREATE TABLE sets (
  set_code         TEXT PRIMARY KEY,              -- 'SV2A', 'M2A' (uppercase)
  era_block        TEXT NOT NULL,                 -- 'SV', 'M', 'S', 'SM', 'XY', ...
  language         TEXT NOT NULL DEFAULT 'jp',
  name_ja          TEXT,
  name_en          TEXT,
  release_date     DATE,
  total            INTEGER,                       -- including secret rares
  parent_set_code  TEXT REFERENCES sets(set_code),-- e.g. M2A → M2
  tcgdex_id        TEXT,                          -- nullable; set-id at TCGdex if known
  source_refs      JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sets_era_block ON sets (era_block);
CREATE INDEX idx_sets_release_date ON sets (release_date DESC);

-- =========================================================
-- cards: one row per (set, local_id, variant)
-- =========================================================
CREATE TABLE cards (
  card_id          TEXT PRIMARY KEY,              -- 'jp-sv2a-163-normal'
  set_code         TEXT NOT NULL REFERENCES sets(set_code),
  local_id         TEXT NOT NULL,                 -- '163'  (3-digit padded)
  variant          TEXT NOT NULL DEFAULT 'normal',-- 'normal','master_ball_mirror',...
  rarity_code      TEXT,                          -- 'C','U','R','RR','AR','SR','SAR','UR','MUR','MA',...
  name_ja          TEXT NOT NULL,
  name_en          TEXT,
  image_url        TEXT,
  category         TEXT NOT NULL DEFAULT 'card',  -- 'card','sealed','accessory'
  is_tracked       BOOLEAN NOT NULL DEFAULT true,
  source_refs      JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_cards_set_local_variant
  ON cards (set_code, local_id, variant);
CREATE INDEX idx_cards_set_code    ON cards (set_code);
CREATE INDEX idx_cards_rarity_code ON cards (rarity_code);
CREATE INDEX idx_cards_is_tracked  ON cards (is_tracked) WHERE is_tracked = true;
```

Notes:
- `card_id` is a human-readable slug built as `jp-{lower(set_code)}-{local_padded}-{variant}`. Examples:
  - `jp-sv2a-089-normal`
  - `jp-sv2a-163-master_ball_mirror`
  - `jp-m2a-226-normal` (MA secret rare beyond official total)
- `source_refs` carries per-source provenance without schema churn, e.g. `{"tcgdex": "sv2a-089", "cardrush": {"product_id": 43430, "seen_at": "2026-04-21T12:00Z"}}`.
- `price_points`, `scrape_runs`, `card_scrape_state` keep their existing DDL; rows are wiped on migration.

---

## Rarity codes (canonical list)

Source of truth: `packages/catalog/watari_catalog/rarities.py`.

```python
RARITY_ORDER: tuple[str, ...] = (
    "C", "U", "R", "RR",
    "AR", "SR", "SAR",
    "UR", "MUR", "MA",
    "SIR",
    "HR", "CHR", "CSR", "RRR",  # future / older eras
)

# TCGdex serves English words; map to our code.
TCGDEX_RARITY_MAP: dict[str, str] = {
    "Common": "C",
    "Uncommon": "U",
    "Rare": "R",
    "Double Rare": "RR",
    "Art Rare": "AR",
    "Super Rare": "SR",
    "Special Art Rare": "SAR",
    "Ultra Rare": "UR",
    "Shiny Rare": "SIR",
    "Hyper Rare": "HR",
    # ... extended per era as needed
}

# Cardrush renders rarity inside 【…】 brackets; identity map with "-" meaning "no rarity" (variant).
CARDRUSH_TAG_MAP: dict[str, str | None] = {r: r for r in RARITY_ORDER}
CARDRUSH_TAG_MAP["-"] = None
```

Unknown inputs → log a WARNING and store `NULL`. We extend the map as new codes surface (e.g. pokeguardian covers HR/CHR/CSR/RRR for Sword & Shield).

---

## Variant slugs

Source of truth: `packages/catalog/watari_catalog/variants.py`.

```python
DEFAULT_VARIANT = "normal"

# Japanese parenthesized marker (from Cardrush name) → stable slug.
VARIANT_SLUGS: dict[str, str] = {
    "マスターボールミラー":   "master_ball_mirror",
    "モンスターボールミラー":  "poke_ball_mirror",
    "ポケモンボールミラー":   "poke_ball_mirror",
    "ダークボールミラー":    "dark_ball_mirror",
    "フレンドボールミラー":   "friend_ball_mirror",
    "クイックボールミラー":   "quick_ball_mirror",
    "ラブラブボールミラー":   "love_ball_mirror",
    "リバースホロ":         "reverse_holo",
    "R団ミラー":            "rocket_mirror",
    "R仕様":                "r_spec",
    "炎エネルギーミラー":    "energy_mirror_fire",
    "水エネルギーミラー":    "energy_mirror_water",
    "雷エネルギーミラー":    "energy_mirror_lightning",
    "草エネルギーミラー":    "energy_mirror_grass",
    "超エネルギーミラー":    "energy_mirror_psychic",
    "闘エネルギーミラー":    "energy_mirror_fighting",
    "悪エネルギーミラー":    "energy_mirror_darkness",
    "鋼エネルギーミラー":    "energy_mirror_metal",
    "竜エネルギーミラー":    "energy_mirror_dragon",
    "無色エネルギーミラー":   "energy_mirror_colorless",
}
```

TCGdex exposes `variants.reverse`; when true we synthesize a second `cards` row with `variant='reverse_holo'`. Unknown JP markers → `variant="unknown"`, warning logged with context so we extend the registry.

Slugs are sticky (they live in `card_id`). **Treat them as API.**

---

## Package layout

```
packages/catalog/
├── pyproject.toml           # curl_cffi, httpx, beautifulsoup4, pyyaml, sqlalchemy[asyncio]
└── watari_catalog/
    ├── __init__.py
    ├── __main__.py          # CLI: seed-sets | enrich-tcgdex | discover-cardrush | verify
    ├── rarities.py
    ├── variants.py
    ├── parser.py            # parse_cardrush_product_name(...)
    ├── cardrush_client.py   # curl_cffi Session + paginator
    ├── tcgdex_client.py     # httpx async wrapper (per-card endpoint)
    ├── seed_sets.py         # YAML → sets table
    ├── enrich_tcgdex.py     # TCGdex → fill name_en, image, illustrator, rarity_code
    ├── discover_cardrush.py # Cardrush → upsert cards/variants, fill JP gaps
    ├── verify.py            # coverage report
    └── sets.yml             # curated set registry (human-owned)
```

---

## `sets.yml` seed (committed in repo)

Each entry is minimal. Unknown release dates are OK — they can be filled later.

```yaml
# --- Scarlet & Violet block ---
- { set_code: SV1S,  era_block: SV, name_ja: スカーレットex,          tcgdex_id: SV1S }
- { set_code: SV1V,  era_block: SV, name_ja: バイオレットex,          tcgdex_id: SV1V }
- { set_code: SV2A,  era_block: SV, name_ja: ポケモンカード151,         tcgdex_id: SV2A }
- { set_code: SV2P,  era_block: SV, name_ja: スノーハザード,           tcgdex_id: SV2P }
- { set_code: SV2D,  era_block: SV, name_ja: クレイバースト,           tcgdex_id: SV2D }
- { set_code: SV3,   era_block: SV, name_ja: 黒炎の支配者,             tcgdex_id: SV3  }
- { set_code: SV3A,  era_block: SV, name_ja: レイジングサーフ,          tcgdex_id: SV3A }
- { set_code: SV4K,  era_block: SV, name_ja: 古代の咆哮,              tcgdex_id: SV4K }
- { set_code: SV4M,  era_block: SV, name_ja: 未来の一閃,              tcgdex_id: SV4M }
- { set_code: SV4A,  era_block: SV, name_ja: シャイニートレジャーex,    tcgdex_id: SV4A }
- { set_code: SV5K,  era_block: SV, name_ja: ワイルドフォース,          tcgdex_id: SV5K }
- { set_code: SV5A,  era_block: SV, name_ja: サイバージャッジ,          tcgdex_id: SV5A }
- { set_code: SV6,   era_block: SV, name_ja: 変幻の仮面,              tcgdex_id: SV6  }
- { set_code: SV7,   era_block: SV, name_ja: スターレットスター,        tcgdex_id: SV7  }
- { set_code: SV7A,  era_block: SV, name_ja: パラダイムトリガー,        tcgdex_id: SV7A }
- { set_code: SV8,   era_block: SV, name_ja: 超電ブレイカー,            tcgdex_id: SV8  }
- { set_code: SV8A,  era_block: SV, name_ja: テラスタルフェスex,        tcgdex_id: SV8A }
- { set_code: SV9,   era_block: SV, name_ja: バトルパートナーズ,         tcgdex_id: SV9  }
- { set_code: SV9A,  era_block: SV, name_ja: 熱風のアリーナ,            tcgdex_id: SV9A }
- { set_code: SV10,  era_block: SV, name_ja: ロケット団の栄光,          tcgdex_id: SV10 }
- { set_code: SV11W, era_block: SV, name_ja: ブラックボルト,            tcgdex_id: SV11W }
- { set_code: SV11B, era_block: SV, name_ja: ホワイトフレア,            tcgdex_id: SV11B }
- { set_code: SVK,   era_block: SV, name_ja: スターターデッキ・プロモ,   tcgdex_id: SVK  }
- { set_code: SVLN,  era_block: SV, name_ja: リーフィアex スターターセット, tcgdex_id: SVLN }
- { set_code: SVLS,  era_block: SV, name_ja: グレイシアex スターターセット, tcgdex_id: SVLS }

# --- Mega Evolution block ---
- { set_code: M1S,   era_block: M,  name_ja: メガシンフォニア,           tcgdex_id: M1S  }
- { set_code: M2,    era_block: M,  name_ja: インフェルノX,             tcgdex_id: null }  # missing in TCGdex as of probe
- { set_code: M2A,   era_block: M,  name_ja: MEGAドリームex, parent_set_code: M2, tcgdex_id: null }
- { set_code: M3,    era_block: M,  name_ja: ムニキスゼロ,              tcgdex_id: M3   }
```

`release_date` and `total` are populated by enrichment + discovery, not by hand.

---

## Pipeline stages

Each stage is a single command, idempotent, runs independently.

### 1. `seed-sets`
Loads `sets.yml` → upserts into `sets` table. Zero network. Fast.

### 2. `enrich-tcgdex`
For every set with a non-null `tcgdex_id`:
1. Fetch `/v2/ja/sets/{tcgdex_id}` (set metadata + card list).
2. For each card, fetch `/v2/ja/cards/{tcgdex_id}-{localId}` (full per-card).
3. Upsert one row per card with `variant='normal'`, plus a second row with `variant='reverse_holo'` when `variants.reverse == true`.
4. Write fields: `name_ja`, `name_en`, `image_url`, `category`, `rarity_code` (via `TCGDEX_RARITY_MAP`), `local_id` (3-digit padded), `source_refs.tcgdex`.
5. Update parent `sets` row with `release_date`, `total` if missing.

### 3. `discover-cardrush`
For every `set_code` in `sets`:
1. Paginate `https://www.cardrush-pokemon.jp/product-list?keyword={set_code}&page={n}` with `curl_cffi` (Chrome impersonate) until a page adds no new product URLs.
2. For each `.list_item_cell`:
   - `goods_name` (→ parse name, rarity tag, local_id, variant marker, condition prefix ignored at catalog layer).
   - `model_number_value` (authoritative set code disambig — skip rows where it ≠ current `set_code`).
   - `href` on `.item_data_link` (product detail URL).
3. Upsert one row per `(set_code, local_id, variant)` with `name_ja`, `rarity_code`, `variant`, `category='card'`, `source_refs.cardrush`. Never overwrite fields populated by TCGdex (use `COALESCE` / conditional SET).
4. Unknown variant marker → `variant="unknown"`, warning logged.

### 4. `verify`
Reports, per set:
- card count
- % with `rarity_code`
- % with `name_en`
- % with `image_url`
- distinct variants observed
- anomalies (duplicate local_ids, missing `name_ja`, etc.)

Exits non-zero if any critical invariant fails.

---

## CLI ergonomics

```bash
# First-time build
uv run python -m watari_catalog seed-sets
uv run python -m watari_catalog enrich-tcgdex                   # all eligible sets
uv run python -m watari_catalog discover-cardrush --all         # fills JP gaps
uv run python -m watari_catalog verify

# Per-set targeted runs
uv run python -m watari_catalog enrich-tcgdex --set SV2A
uv run python -m watari_catalog discover-cardrush --set M2A

# Dry run
uv run python -m watari_catalog discover-cardrush --set SV2A --dry-run
```

---

## Alembic migration `003_catalog_v2`

Single transaction, destructive:

1. `DROP MATERIALIZED VIEW IF EXISTS mv_cross_source_spread, mv_median_7d, mv_latest_price`.
2. `TRUNCATE price_points, card_scrape_state, scrape_runs, cards RESTART IDENTITY CASCADE`.
3. `DROP TABLE cards`.
4. `CREATE TABLE sets (…)` + indexes.
5. `CREATE TABLE cards (…)` + indexes (new shape).
6. Re-create the three materialized views (unchanged DDL, they join only `price_points` and `cards`).

`downgrade()` is best-effort (restores prior schema, no data).

---

## Testing strategy

- `tests/unit/test_catalog_parser.py` — Cardrush name-grammar cases (normal/variant/secret/sealed/condition-prefix/unknown-variant/rarity-dash).
- `tests/unit/test_rarity_map.py` — TCGdex English → code, Cardrush tag → code.
- `tests/unit/test_variant_slugs.py` — registry round-trip, unknown handling.
- `tests/unit/test_card_id.py` — `build_card_id(set_code, local_id, variant)` padding/casing invariants.
- Integration smoke (optional, manual): `enrich-tcgdex --set SV2A` + `discover-cardrush --set SV2A` + `verify --set SV2A` all pass.

---

## Acceptance criteria

- `sets` has ≥ 29 rows (all SV + M1S/M2/M2A/M3).
- `cards` has ≥ 4,500 rows across all sets (estimate).
- `M2A` has ≥ 1 row with `rarity_code='MA'`.
- `M2` and `M2A` both reach `cards` via `discover-cardrush` even though TCGdex has no data.
- `SELECT COUNT(*) FROM cards WHERE rarity_code IS NULL AND category='card' AND variant='normal'` is 0 for SV/M sets (every numbered normal card has a rarity).
- ≥ 95% of SV-block cards have `name_en` and `image_url` from TCGdex.
- `discover-cardrush --all` run twice produces identical rowcount (idempotent).
- `verify` exits 0.
- All unit tests pass; ruff + mypy clean.

---

## Out of scope (follow-ups)

- **`cardrush-scraper-rewrite.md`** — migrate price scraper from Playwright → `curl_cffi`, rarity-bucket driven, variant-aware card lookup.
- **SNKRDUNK rewrite** — align with new catalog (match by `card_id` + `variant`; resolve apparel_id once per card into `source_refs.snkrdunk`).
- **pokemon-card.com cross-check** — authoritative JP release dates / set totals.
- **English name enrichment** for sets TCGdex misses (M2/M2A) — manual or pokellector scrape.
- **Sealed product pricing** — schema supports `category='sealed'`; ingestion deferred.

---

## Research notes (for reference)

### Source comparison

| Source          | JP set coverage | Rarity | Variants    | EN names | Images |
|-----------------|-----------------|--------|-------------|----------|--------|
| TCGdex per-card | lags ~3–6 mo    | ✅     | partial     | ✅       | ✅     |
| Cardrush (curl_cffi) | day-0      | ✅ (JP tag) | ✅ (rich) | ❌       | ✅ thumb |
| SNKRDUNK        | lags; lookup    | ❌     | ❌          | ❌       | ✅     |
| pokemon-card.com | day-0 (official) | ✅    | ✅         | ❌       | ✅     |

### Missing-in-TCGdex (as of probe)

- `M2` インフェルノX — 80 official cards
- `M2A` MEGAドリームex — 193 official + secret rares (e.g. MA 226/193)

### Rarity taxonomy observed (Cardrush)

| Era   | Rarities |
|-------|----------|
| SV    | C, U, R, RR, AR, SR, SAR, UR (+ SIR in late sets) |
| MEGA (M1S, M3) | C, U, R, RR, AR, SR, SAR, MUR |
| MEGA (M2, M2A) | C, U, R, RR, AR, SR, SAR, MUR, **MA** |

### Cardrush HTTP posture

- Plain `curl`/`httpx` → HTTP 403, `cf-mitigated: challenge`.
- `curl_cffi` with `impersonate='chrome120'` → HTTP 200, 390 KB real HTML, no challenge.
- **Verdict**: no browser, no Playwright, no stealth patches required.
