# Plan — Catalog v3 (YML data contract, artwork/print split)

**Status**: draft, awaiting approval before implementation
**Scope**: Redesign the catalog so metadata is a committed-to-git YML tree, and split artwork from print so prices (per variant) don't duplicate images/names.
**Supersedes**: the "multi-source-live" portion of `catalog-metadata.md` for SV + ME. (That plan's schema work stays; discovery pipeline is retired for these eras.)

---

## What changes and why

The current catalog has three coupled problems:

1. **Metadata duplicated per variant.** Every print of Mewtwo (normal, master-ball, poke-ball) carries its own `image_url`, `name_ja`, `rarity_code`. The mirrors inherit Cardrush's ugly 160-px product thumbnails because pokellector/tcgdex don't split them.
2. **Metadata is "live".** `enrich-tcgdex` + `discover-cardrush` run against the network each time. A deterministic rebuild is hard to reason about and lags source outages.
3. **`sets.yml` holds only set-level info.** Card-level data lives in the DB only, so a card's "correct" name/rarity can't be reviewed in a PR.

For SV + Mega eras this is unnecessary: **the cards don't change after release** (the only exception is JP PROMO, which is out of scope for this plan). Fixing it once and locking it in git is cheaper than re-deriving from three scrapers on every run.

Three decoupled changes:

| concern | before | after |
|---|---|---|
| what exists | live scrape per run | committed YML tree, file-per-card |
| artwork vs print | fused in one `cards` row per variant | `artworks` + `cards` tables |
| prices | scraper → `price_points` (unchanged) | scraper → `price_points` (unchanged) |

Bootstrap uses the sources we already proved out (Pokellector primary, TCGdex fallback, Cardrush for variant list). After the bootstrap commit, catalog builds are **network-free**.

---

## Schema v3

Keep `sets` as it is. Split `cards` into two tables.

```sql
-- =========================================================
-- sets: unchanged (see 003_catalog_v2)
-- =========================================================

-- =========================================================
-- artworks: one row per (set_code, local_id).
-- Artwork-level identity. Owns image, names, rarity.
-- =========================================================
CREATE TABLE artworks (
  artwork_id       TEXT PRIMARY KEY,              -- 'jp-sv2a-150'
  set_code         TEXT NOT NULL REFERENCES sets(set_code),
  local_id         TEXT NOT NULL,                 -- '150'  (3-digit padded)
  name_ja          TEXT NOT NULL,
  name_en          TEXT,
  rarity_code      TEXT,                          -- 'C','U','R','AR','SR','SAR','UR','MA',...
  image_url        TEXT,
  category         TEXT NOT NULL DEFAULT 'card',  -- 'card','trainer','energy'
  illustrator      TEXT,                          -- nullable; filled from pokellector/tcgdex when present
  source_refs      JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_artworks_set_local ON artworks (set_code, local_id);
CREATE INDEX idx_artworks_set_code    ON artworks (set_code);
CREATE INDEX idx_artworks_rarity_code ON artworks (rarity_code);

-- =========================================================
-- cards: one row per PRINT (artwork × variant).
-- Price-discovery concern. No metadata duplication.
-- =========================================================
CREATE TABLE cards (
  card_id          TEXT PRIMARY KEY,              -- 'jp-sv2a-150-normal'
  artwork_id       TEXT NOT NULL REFERENCES artworks(artwork_id),
  set_code         TEXT NOT NULL REFERENCES sets(set_code),  -- denormalized for fast filters
  local_id         TEXT NOT NULL,                 -- denormalized
  variant          TEXT NOT NULL DEFAULT 'normal',-- 'normal','master_ball_mirror',...
  is_tracked       BOOLEAN NOT NULL DEFAULT true,
  source_refs      JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_cards_set_local_variant ON cards (set_code, local_id, variant);
CREATE INDEX idx_cards_artwork_id ON cards (artwork_id);
CREATE INDEX idx_cards_set_code   ON cards (set_code);
CREATE INDEX idx_cards_is_tracked ON cards (is_tracked) WHERE is_tracked = true;
```

`price_points` is unchanged — it still references `cards.card_id`, which is the print-level id. Downstream code doesn't break.

Key invariants:
- `cards.artwork_id = 'jp-{set}-{local_id}'` always.
- `cards.card_id = '{artwork_id}-{variant}'` always.
- Every `artwork` has at least one `card` (the `normal` print).
- `image_url`, `name_*`, `rarity_code` live ONLY on `artworks`. Variants never duplicate them.
- To render a print, join `cards` → `artworks` and compose the display label from `artwork.name_ja` + variant suffix.

Migration strategy: destructive again. We've been running on v2 for ~1 day; re-seeding is cheap. Materialized views are re-created against the new join.

### What gets dropped from the old `cards`

- `name_ja`, `name_en`, `rarity_code`, `image_url`, `category` → moved to `artworks`.
- `rarity_code` index on `cards` → moved to `artworks`.

`source_refs` is kept on both tables (artwork-level refs vs print-level refs are different things).

---

## YML tree (source of truth)

File-per-card, set-scoped directories. Committed in git, reviewed via PR, no network needed to build the DB.

```
packages/catalog/data/
├── sets/
│   ├── sv1.yml
│   ├── sv2a.yml
│   ├── ...
│   ├── m1.yml
│   └── m2a.yml
└── cards/
    ├── sv2a/
    │   ├── 001.yml            # Bulbasaur  (normal + 2 mirrors)
    │   ├── 006.yml            # Charizard ex
    │   ├── 150.yml            # Mewtwo
    │   ├── 183.yml            # Mewtwo AR
    │   ├── 196.yml            # Erika's Invitation SR
    │   └── 210.yml
    ├── m2a/
    │   ├── 001.yml
    │   └── ...
    └── ...
```

### Set file shape

```yaml
# packages/catalog/data/sets/sv2a.yml
set_code: SV2A
era_block: sv
language: jp
name_ja: ポケモンカード151
name_en: Pokemon Card 151
release_date: 2023-06-16
total_base: 165
total_with_secrets: 210
parent_set_code: null
sources:
  tcgdex: { id: sv2a }
  pokellector: { slug: Pokemon-151-Expansion, series_id: 371 }
# Optional variant defaults for the set. Bootstrap uses these so individual
# card files don't repeat them. Can be overridden per card.
variant_rules:
  - applies_to: { local_id_range: [1, 165] }
    variants: [normal, master_ball_mirror, poke_ball_mirror]
  - applies_to: { local_id_range: [166, 210] }
    variants: [normal]
```

### Card file shape (artwork + prints)

```yaml
# packages/catalog/data/cards/sv2a/150.yml
local_id: "150"
name_ja: ミュウツー
name_en: Mewtwo
rarity_code: R
category: card
illustrator: null
image: https://den-cards.pokellector.com/371/Mewtwo.SV2A.150.48449.png
prints:
  - normal
  - master_ball_mirror
  - poke_ball_mirror
sources:
  pokellector: { id: 48449, series_id: 371, slug: Mewtwo-Card-150 }
  tcgdex:      { id: SV2a-150, raw_rarity: Rare }
```

```yaml
# packages/catalog/data/cards/sv2a/183.yml  (AR — no mirror prints)
local_id: "183"
name_ja: ミュウツー
name_en: Mewtwo
rarity_code: AR
category: card
image: https://den-cards.pokellector.com/371/Mewtwo.SV2A.183.48579.png
prints:
  - normal
sources:
  pokellector: { id: 48579, series_id: 371, slug: Mewtwo-Card-183 }
  tcgdex:      { id: SV2a-183, raw_rarity: Art Rare }
```

Rules:
- `local_id` is a string, zero-padded to 3 digits. File name matches.
- `rarity_code` uses our canonical table (`C`, `U`, `R`, `RR`, `AR`, `SR`, `SAR`, `UR`, `MUR`, `MA`, …).
- `prints` is a list of variant slugs from `variants.py`. `normal` is required.
- `image` is a single URL. Pokellector preferred; TCGdex `/high.png` as fallback.
- `sources` is free-form provenance — not used at runtime, but helps humans trace where a value came from.

---

## Bootstrap pipeline (run once per set; output committed)

One-shot script that fills `packages/catalog/data/cards/{set}/*.yml` from all three sources. After the bootstrap, catalog builds never hit the network again for SV + ME.

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│ Pokellector  │      │   TCGdex     │      │   Cardrush   │
│ (primary:    │      │ (fallback:   │      │ (variants:   │
│  name_en,    │      │  rarity,     │      │   which      │
│  image, JP)  │      │  illustrator)│      │   prints     │
└──────┬───────┘      └──────┬───────┘      │   exist)     │
       │                     │              └──────┬───────┘
       ▼                     ▼                     ▼
              ┌───────────────────────────┐
              │   merge + dedupe          │
              │   (pokellector wins for   │
              │    image/name; tcgdex     │
              │    wins for illustrator)  │
              └───────────────┬───────────┘
                              ▼
              ┌───────────────────────────┐
              │  write YML per card       │
              │  +  diff vs. current git  │
              │  (manual review)          │
              └───────────────────────────┘
```

Implementation slot:

```
packages/catalog/pokeprice_catalog/
├── bootstrap/
│   ├── __init__.py
│   ├── pokellector_client.py    # new: plain httpx, no curl_cffi
│   ├── merge.py                 # per-card merge logic with source precedence
│   └── emit_yml.py              # round-trip-stable YAML writer
└── __main__.py                  # + bootstrap-set [--set SV2A]
```

The bootstrap is re-runnable. When TCGdex adds a late-arriving set, we re-run and regenerate the YMLs, then diff.

### Variant list: how we decide

1. Default to `variant_rules` in the set YML (`variant_rules` per local_id range).
2. Cardrush discovery results (cached in MinIO bronze) refine per-card overrides if the set rule is wrong.
3. Unknown variant markers surface as a bootstrap warning so humans can edit the YML or extend `variants.py`.

After bootstrap, Cardrush is **only** a price source (see `cardrush-scraper-rewrite.md`). The runtime scraper reads variants from the DB (`cards` table, populated from YML) and doesn't touch the catalog.

---

## Build pipeline (runtime)

Replaces the existing multi-stage enrichment. Network-free after bootstrap.

```bash
# One-time per-set bootstrap (generates YML, commits to git):
uv run python -m pokeprice_catalog bootstrap-set --set SV2A
# ...review diff, commit...

# Runtime build of the DB (idempotent, no network):
uv run python -m pokeprice_catalog seed-sets          # sets/*.yml → sets table
uv run python -m pokeprice_catalog seed-cards          # cards/*.yml → artworks + cards
uv run python -m pokeprice_catalog verify
```

`seed-cards` reads the YML tree top-down:
1. For each `data/cards/{set}/{local_id}.yml` → upsert `artworks` row.
2. For each `prints` entry → upsert `cards` row.
3. Prune: delete `cards` rows not in the YML (safe — `price_points` references are handled via FK, and pruning is guarded by a `--no-prune` flag).

`verify` asserts:
- every `artworks` row has ≥ 1 `cards` row
- every `cards` row has a valid `artworks` FK
- every tracked set in `sets.yml` has at least one `artworks` row
- rarity/variant values are in the canonical registries

---

## Alembic migration `005_artworks_split`

Single transaction, destructive:

1. Drop the three materialized views.
2. Truncate `price_points`, `card_scrape_state`, `scrape_runs`.
3. Drop FKs from `price_points.card_id` and `card_scrape_state.card_id`.
4. Drop `cards` (old shape).
5. Create `artworks` + new `cards` (split) with indexes.
6. Re-add FKs from `price_points` / `card_scrape_state` to new `cards.card_id`.
7. Re-create the three materialized views — they now join through `artworks` when they need image/name.

`downgrade()` is best-effort (no data restore).

---

## Scope / acceptance

**In scope (first PR):**
- Schema migration `005_artworks_split`.
- Python ORM models for `Artwork` + updated `Card`.
- Pydantic DTOs updated.
- `seed-cards` CLI + `verify` refresh.
- Bootstrap script + first complete YML tree for **SV2A** and **M2A** (to prove both eras and the MA rarity).
- Tests: YML loader round-trip, rarity/variant canonicalization, seed idempotency.

**Second PR (same plan):**
- Bootstrap the remaining 20+ SV sets and 4 ME sets.
- Human review pass.
- Delete `enrich_tcgdex.py` + `discover_cardrush.py` from the catalog package (Cardrush moves 100% to price-discovery role).

**Out of scope:**
- PROMO sets (living data — handled later with a different workflow).
- Pre-SV eras (SM, XY, etc.) — can reuse the same pipeline when we're ready.
- English-language-only `cards` (en.pokellector.com) — we're JP-first.
- API/read-side changes beyond what's needed to keep the existing scraper + price queries working.

**Acceptance criteria:**
- `artworks` has 210 rows for SV2A, matching pokellector set total.
- `cards` has ~516 rows for SV2A (210 + 153 MBM + 153 PBM, approximately — matches current `v2` rowcount).
- `SELECT image_url FROM artworks WHERE image_url IS NULL` → 0 rows for SV2A + M2A.
- `SELECT name_en FROM artworks WHERE name_en IS NULL` → 0 rows for SV2A + M2A.
- Running the existing Cardrush scraper against SV2A still writes into `price_points` correctly.
- `seed-cards` run twice leaves the DB bit-identical (idempotent).

---

## Open questions (to answer before coding)

1. **YAML library.** `pyyaml` (current) vs. `ruamel.yaml` (round-trip-stable, preserves comments). For a bootstrap writer we want stability; proposal: `ruamel.yaml` for writing, plain `pyyaml` for reading is fine.
2. **Diff-in-place vs. regenerate-and-diff.** First bootstrap obviously regenerates. Subsequent re-runs: do we overwrite, or merge while preserving hand edits? Proposal: overwrite with a `--preserve-manual-edits` flag that respects a `# manual: true` comment per YML.
3. **Illustrator.** Pokellector doesn't expose it, TCGdex does. Accept NULL when TCGdex lacks the set (M2/M2A).
4. **Mirror image for display.** We said one image per artwork — confirmed with user. Front-end composes a label suffix for the variant rather than showing a different image.
5. **ME era English names.** TCGdex lacks M2/M2A; Pokellector does have them (`MEGA Dream ex`, card slugs in English). We get these from Pokellector only, which is fine per source precedence.

---

## Risks

- **Pokellector is scraped, unofficial.** Mitigate by caching every fetched HTML/AJAX page to MinIO (`bronze/pokellector/...`) during bootstrap so we can re-emit without hitting the site again.
- **Rate limits.** Be polite: UA header, 250–500 ms jitter between requests, retry with backoff. The set-page fetch + one AJAX call per card = ~210 requests per set, spread over a minute — trivial.
- **Set-code mismatches.** Pokellector uses its own URL slugs (`Pokemon-151-Expansion`). We keep our own `set_code` authoritative and map it explicitly in each `sets/*.yml` under `sources.pokellector.slug`.
- **YML churn.** Once committed, card files should be near-immutable. Any change to a card file is a meaningful PR (e.g. "TCGdex finally added M2A → fill illustrator").

---

## Example: what the final tree looks like for SV2A (partial)

```
packages/catalog/data/sets/sv2a.yml
packages/catalog/data/cards/sv2a/
├── 001.yml  # フシギダネ Common,  prints: [normal, master_ball_mirror, poke_ball_mirror]
├── 002.yml  # フシギソウ Common
├── 003.yml  # フシギバナex RR
├── ...
├── 150.yml  # ミュウツー R,  prints: [normal, master_ball_mirror, poke_ball_mirror]
├── 151.yml  # ミュウex RR
├── ...
├── 165.yml  # サイクリングロード Uncommon (last base card)
├── 166.yml  # フシギダネ AR, prints: [normal]
├── ...
├── 183.yml  # ミュウツー AR,  prints: [normal]
├── 184.yml  # フシギバナex SR, prints: [normal]
├── ...
├── 200.yml  # フシギバナex SAR
├── ...
└── 210.yml  # サイキックエネルギー UR
```

~210 files per major set. A review PR per set is perfectly readable.
