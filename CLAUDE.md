# CLAUDE.md — Project State & Roadmap

> **Purpose:** this file is the handoff note for the next Claude session.
> It captures "what the codebase is", "what just landed", "what's next",
> and the handful of invariants that are easy to break.
> Update it whenever the architecture changes — especially after a
> destructive migration, a new source, or a schema split.
>
> Last updated: 2026-04-24 (Full SV + ME seed + M1 → M1L rename: all 28 sets bootstrapped, card YML tree complete, 117k `price_points` across Cardrush + SNKRDUNK, MVs populated).

---

## 1. Project TL;DR

Universal Pokémon TCG price API for the **Japanese** market.

Three concerns, cleanly separated:

| Layer       | Responsibility                                                           | Code                                        |
| ----------- | ------------------------------------------------------------------------ | ------------------------------------------- |
| **Catalog** | What cards exist (sets, artworks, print variants). Source of truth: YML. | `packages/catalog/`, `data/`                |
| **Prices**  | Listings (`cardrush`) + sold comps (`snkrdunk`) → `price_points`.        | `packages/scraper_cardrush/`, `…_snkrdunk/` |
| **API**     | Read-side (FastAPI). Uses materialized views for latency.                | `packages/api/`                             |

Stack: Python 3.13, `uv` workspaces, PostgreSQL, SQLAlchemy async, Alembic,
MinIO (S3-compatible) for the **bronze layer** of raw scrape payloads,
`curl_cffi` for Cloudflare-fronted sites, `httpx` for everything else.

---

## 2. Repo layout

```
packages/
  core/                ← SQLAlchemy models, Pydantic DTOs, catalog.py helpers, bronze writer
  catalog/             ← YML data tree + bootstrap/seed pipeline + CLI
    data/
      sets/*.yml       ← 28 set files (source of truth for set metadata)
      cards/{SET}/*.yml← one file per (set, local_id); source of truth for artworks
    pokeprice_catalog/ ← Python package (bootstrap.py, seed_cards.py, clients, …)
  scraper_cardrush/    ← curl_cffi-based scraper, rarity-bucket crawling
  scraper_snkrdunk/    ← cookie-auth snkrdunk sold-price scraper
  dispatcher/          ← job dispatch (placeholder-ish for now)
  scheduler/           ← cron/apscheduler shell (placeholder-ish for now)
  api/                 ← FastAPI read layer
migrations/            ← Alembic (current head: 005_artworks_split)
plans/                 ← design docs, one per major change
tests/unit/            ← 120 tests, all passing
```

Config knobs: `.env` (DB URL, MinIO creds, SNKRDUNK cookies). `docker-compose.yml`
brings up Postgres + MinIO.

---

## 3. Current architecture — Catalog v3 (shipped)

### 3.1 Schema (post-migration `006_mv_spread_unique_index`)

```
sets        ── 1 row per set (set_code PK). source_refs.pokellector_slug is required for bootstrap.
artworks    ── 1 row per (set_code, local_id). Owns name_ja/en, image_url, rarity_code,
               illustrator, category. artwork_id = "jp-{set_code_lower}-{local_id_padded}".
cards       ── 1 row per print (set_code, local_id, variant). artwork_id FK → artworks.
               card_id = "{artwork_id}-{variant}". price_points.card_id FKs here.
price_points, card_scrape_state, scrape_runs ← unchanged in shape.
mv_latest_price, mv_median_7d, mv_cross_source_spread ← rebuilt by the migration.
             All three have a UNIQUE index so REFRESH MATERIALIZED VIEW
             CONCURRENTLY works (006 added the one for mv_cross_source_spread).
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
# SV2A #089. Generated by `python -m pokeprice_catalog bootstrap-set`.
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

Helpers live in `packages/core/pokeprice_core/catalog.py`
(`make_artwork_id`, `make_card_id`, `parse_card_id`, `artwork_id_for_card`,
`parse_artwork_id`, `pad_local_id`).

**Watch out:** `parse_artwork_id` / `parse_card_id` split on `"-"` and assume
exactly 3 / 4 segments. If a set_code ever contains a hyphen (e.g. `"sv-p"`)
they will misparse. None of the current 28 set codes contain hyphens.

### 3.5 API layer (`packages/api/`, read-only)

Built on FastAPI. Thin read layer over the v3 catalog + materialized views.
The ORM session is provided per-request via `Annotated[AsyncSession, Depends(get_session)]` aliased as `SessionDep`.

Routers (all under `packages/api/pokeprice_api/routers/`):

| Route                                                               | Returns                 | Source                          |
| ------------------------------------------------------------------- | ----------------------- | ------------------------------- |
| `GET /healthz`                                                      | `{"status": "ok"}`      | —                               |
| `GET /sets` (`?era=sv`)                                             | `list[SetOut]`          | `sets` table                    |
| `GET /sets/{set_code}`                                              | `SetOut` / 404          | `sets` table (case-insensitive) |
| `GET /sets/{set_code}/cards` (`?variant=&rarity=&tracked_only=`)    | `list[CardWithArtwork]` | `cards ⋈ artworks`              |
| `GET /cards/{card_id}`                                              | `CardWithArtwork` / 404 | `cards ⋈ artworks`              |
| `GET /cards/{card_id}/prices`                                       | `list[LatestPrice]`     | `**mv_latest_price`\*\*         |
| `GET /cards/{card_id}/history` (`?days=&source=&condition=&limit=`) | `list[PricePointOut]`   | `price_points`                  |
| `GET /cards/{card_id}/spread`                                       | `list[SpreadRow]`       | `**mv_cross_source_spread**`    |

**Rules:**

- Latency-sensitive endpoints (`/prices`, `/spread`) read from MVs, not
  `price_points` directly. If you add a new aggregate, add an MV in the
  same Alembic migration that creates it, and refresh it post-scrape.
- Responses for card endpoints use `CardWithArtwork` — artwork-level
  fields (`name_ja`, `rarity_code`, `image_url`, …) are denormalized
  onto the card row so clients don't need to join.

**Auth + rate limiting** (`auth.py`, `ratelimit.py`):

- `X-API-Key` header (name configurable via `settings.api_key_header`).
  Missing → anonymous, `free` tier, rate-limit bucket is `ip:{client_ip}`.
  Present but unknown/revoked → 401. Present and valid → authenticated,
  bucket is `key:{api_key_id}`, tier comes from the DB row.
- `api_keys` stores only `(key_hash = sha256(plaintext), key_prefix, owner_email, tier, last_used_at, revoked_at)`. The plaintext is never
  persisted — CLI issuance prints it once and the caller stores it.
  `last_used_at` is bumped at most once per minute per key.
- Rate limiter: Redis token bucket (Lua script for atomicity). Config:
  `settings.api_rate_limits = "free:60:1.0,paid:600:10.0,admin:6000:100.0"`
  (`tier:capacity:tokens_per_sec`; `free` is mandatory). Installed on
  `app.state.rate_limiter` in the FastAPI lifespan.
- Applied as a **router-level dependency** (`dependencies=[Depends( rate_limit_dep)]`) on every router except `/healthz`. Every rate-limited
  response carries `X-RateLimit-{Tier,Limit,Remaining}`; denied requests
  return **429** with `Retry-After`.

**Run:** `make api` (prod) or `make api-dev` (reload). Entry point is
`pokeprice-api` console script → `pokeprice_api/__main__.py:main` →
`pokeprice_api.cli:main`.

**CLI subcommands:**

- `pokeprice-api serve [--host --port --reload]` — run uvicorn (also the
  implicit default, so legacy top-level flags still work).
- `pokeprice-api create-key --owner EMAIL [--tier free|paid|admin]` —
  mints a key; prints the plaintext exactly once. Store only the hash.
- `pokeprice-api revoke-key PREFIX` — sets `revoked_at` by key prefix.
- `pokeprice-api list-keys [--include-revoked]` — metadata-only listing.
- `pokeprice-api refresh-mvs [--no-concurrently]` — manually refresh the
  three price MVs. Handy after a catalog reseed, after importing a
  historical dump, or when a scrape hook failure left the MVs stale.

**Tests:** `tests/unit/test_api.py` (12) uses `dependency_overrides` to
swap `get_session` and `rate_limit_dep` for a FakeSession + anonymous
no-op, keeping endpoint-shape tests infra-free. Auth / rate-limit /
CLI / MV helpers have their own files (`test_api_auth.py` 9,
`test_api_ratelimit.py` 8, `test_api_cli.py` 9, `test_mvs.py` 5).
None of the API or MV tests require Postgres or Redis.

### 3.6 Post-scrape MV refresh hook (`packages/core/pokeprice_core/mvs.py`)

The read API's price/spread endpoints query materialized views, not
`price_points`. Those views must be refreshed after each scrape run or
readers see stale data.

**Contract:**

- `refresh_price_mvs(session, *, concurrently=True)` — async; issues
  `REFRESH MATERIALIZED VIEW [CONCURRENTLY] mv_…` + `COMMIT` for each of
  the three views in dependency order (`mv_latest_price` →
  `mv_median_7d` → `mv_cross_source_spread`). One commit per view so
  locks release between views and `mv_cross_source_spread` reads the
  already-refreshed upstream views. Returns the list of names refreshed.
- `refresh_price_mvs_if_needed(*, rows_written, dry_run=False)` — thin
  guard called from scraper orchestrators. Opens its **own** fresh
  session from `async_session_factory` (so it doesn't inherit an open
  transaction from the scrape), skips when `dry_run=True` or
  `rows_written == 0`, and **swallows + logs** any exception. A failed
  refresh must never abort a successful scrape or mask a real error.

**Call sites:**

- `packages/scraper_cardrush/pokeprice_cardrush/run.py::scrape_set` —
  called once after the scrape session closes (after `finish_scrape_run`
  commits). Honors `dry_run`.
- `packages/scraper_snkrdunk/pokeprice_snkrdunk/run.py::scrape_era` —
  same pattern, outside the scrape `async with`.
- `pokeprice-api refresh-mvs` — manual ops command (§3.5).

**Why `CONCURRENTLY`:** each MV has a `UNIQUE` index (added in 005 for
the first two, 006 for `mv_cross_source_spread`) so Postgres takes only
a `SHARE UPDATE EXCLUSIVE` lock — readers stay online. If you ever add
a fourth MV, **create its unique index in the same migration** or
`CONCURRENTLY` will fail.

---

## 4. What works right now

### 4.1 End-to-end smoke (last run 2026-04-24, full SV + ME seed; M1 → M1L rename)

| Step                                               | Result                                                                                         |
| -------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `alembic upgrade head`                             | clean (head = `006_mv_spread_unique_index`)                                                    |
| `make catalog-seed-sets`                           | 28 sets upserted (all 23 SV + 5 ME)                                                            |
| `make catalog-bootstrap SET=<code>` × 28           | all 28 sets bootstrapped; 3992 card YMLs written (SV2A 210 + M2A 250 previously, +26 new sets) |
| `make catalog-seed-cards`                          | 3788 artworks / 4505 prints across 28 sets                                                     |
| `make catalog-verify`                              | 0 orphans · 0 artworks missing img · 299 missing rarity · 243 missing JA (mostly early SV/M2A Commons) |
| `make scrape-cardrush ERA=sv` + `ERA=me` + M1L retry | ~12.7k Cardrush rows across 28 sets (SV3 needed one retry for 5 rarities that hit DNS flake; M1 re-scraped as M1L)     |
| `make scrape-snkrdunk ERA=<code>` × 28             | ~104k SNKRDUNK rows across 27 sets. **SV1 still returns 0 rows** (merged into `sv1v` on SNKRDUNK). **M1L now works** — the prior 0-row run was because we were asking for the wrong code (`pkmn-tcg-m1-*` is empty; the real product namespace is `pkmn-tcg-M1L-*`). |
| `pokeprice-api refresh-mvs` (CONCURRENTLY)         | mv_latest_price 11 219 · mv_median_7d 417 · mv_cross_source_spread 198                          |
| `uv run pytest`                                    | **163 passed**                                                                                 |

### 4.2 Data that's already committed

- `data/sets/*.yml` — all 28 SV + ME sets with `pokellector_slug` filled.
  Three sets renamed to match reality: **M2** `メガディメンション/Mega Dimension` →
  `インフェルノX/Inferno X`, **SV7A** `パラダイムトリガー (Paradigm Trigger, which
  is actually S12a SWSH)` → `楽園ドラゴーナ/Paradise Dragona`, and **M1 → M1L**
  (official Pokémon abbreviation for `メガブレイブ / Mega Brave`; all JP sources —
  pokecahack, tcg-portal.jp, bee-honpo, ポケモンWiki — call it `M1L`).
- `data/cards/{SET}/*.yml` — 3992 files covering all 28 sets. The biggest
  individual sets are SV4A (360), SV2A (210), M2A (250), SV8A (237),
  SV11B/SV11W (174 each), SV3 (141), SV8 (138), SV7 (135), SV6 (133),
  SV9/SV10 (132), M2 (116), SV1/SV1V (108), M1L (92), M1S (90).

### 4.3 Price data in the DB (post-smoke snapshot)

| Aggregate                | Value                                         |
| ------------------------ | --------------------------------------------- |
| `price_points` total     | 117 080 rows                                  |
| Cardrush rows            | ~12 700 (all 28 sets covered)                 |
| SNKRDUNK rows            | ~104 400 (27 sets; only SV1 empty — merged into `sv1v` upstream) |
| Sets with both sources   | 27 / 28                                       |

Per-set breakdown (sample highlights): SV2A 2606 CR + 13529 SD; M2A 528 + 18198;
SV8A 381 + 15051; M1L 211 + 5839; M2 401 + 6465; SV4A 250 + 5109; SV9 493 + 5213;
SV1V 228 + 4923.

MVs populated across all sets, so `/cards/{id}/prices`, `/cards/{id}/history`,
and `/cards/{id}/spread` now return real data for the entire SV + ME universe
(except **SV1** which is Cardrush-only — no spread rows for that one set, since
spread requires ≥2 sources).

---

## 5. Pending / roadmap (in priority order)

### 5.1 Immediate follow-ups (next session can pick up directly)

1. **Investigate SNKRDUNK coverage gap for SV1.**

- SV1 (Scarlet ex) returned 108/108 `not_found`. Manual probe of
  `pkmn-tcg-sv1-001` is empty, but `pkmn-tcg-sv1v-001` works. SNKRDUNK
  appears to list all Scarlet+Violet base-set cards under `SV1V` only;
  SV1's cards might be addressable via a different product-number prefix
  (or might simply be unlisted). Low priority — Cardrush still gives
  ~700 rows for SV1.
- (Previously M1 looked empty here too. That turned out to be wrong
  naming on our side, not a SNKRDUNK gap — the official JP abbreviation
  is **M1L**, not M1. See §6 gotcha #16 and the 2026-04-24 rename.
  M1L now returns 93/93 cards with 5839 SNKRDUNK rows.)

2. **Backfill missing `name_ja`.**

- 243 artworks still lack a Japanese name. Most live in SV4A (88),
  M2A (128) and a handful spread across early SV sets where Cardrush
  doesn't list Commons.
- Option A (preferred): wait for Cardrush to list Commons, re-bootstrap.
- Option B: hand-fill from scans / the official tracker page, with
  `# manual: true` on line 1.
- Option C: add SNKRDUNK as a third name_ja source (heavier: needs cookie
  auth and a separate scraper path since SNKRDUNK doesn't have per-card
  JA name in the sales-history endpoint).

3. **Re-run the weakly-covered rarities in SV3.**

- The initial `ERA=sv` run hit a transient DNS failure during SV3
  (5 rarities dropped). A follow-up `make scrape-cardrush SET=SV3`
  backfilled them (493 new rows), so current state is fine, but future
  full-era runs should consider adding an auto-retry on DNS / Cloudflare
  timeouts at the rarity level before moving on. The
  `pokeprice_cardrush/retry.py` layer already retries transient errors
  once; bumping that to 2–3 would make a full era run self-healing.

4. **Tracked-listings coverage is uneven between Cardrush and SNKRDUNK.**

- Cardrush finds listings for most prints (often 86–516 cards per set)
  but only the actively-listed ones have an in-stock `price_points` row.
- SNKRDUNK resolves ~20–90 apparel IDs per set (you only get rows for
  cards that have actually been sold on SNKRDUNK). That's expected —
  SNKRDUNK is sold-comps only.
- Don't "fix" this by lowering Cardrush's set-disambiguation filter
  (`listings_dropped_wrong_set`); that filter is doing its job.

5. **Known gotcha (unchanged from prior session):** SNKRDUNK for mega-popular
  cards can trip the asyncpg 32767-query-arg limit when writing a card's
  full history in one insert. SV8A and M2A each hit this on 1 card during
  this seeding pass (`attempted=291 succeeded=290` and `attempted=250
  succeeded=249` respectively). Low-priority fix: batch
  `insert_price_points` in chunks of, say, 1000 rows.

### 5.2 Medium-term

- **API polish.** Add pagination (`limit`/`offset`) to `/sets/{code}/cards`,
  E-Tag / `Cache-Control` headers on `/cards/{card_id}/prices` and
  `/spread`, and OpenAPI examples. Consider a `/cards/search?name=...`
  endpoint backed by `artworks.name_ja` + `name_en`.
- **Live rate-limit integration test.** The unit suite stubs Redis via a
  fake limiter. We don't yet have a smoke test that drives the real Lua
  token-bucket against the `docker-compose` Redis. Worth adding once CI
  has service containers.
- **Scheduler + dispatcher.** Currently placeholder packages. Wire up a
  nightly schedule: SNKRDUNK nightly, Cardrush a few times a day per era.

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
12. **Every non-healthz router carries `Depends(rate_limit_dep)` at the
    router level.** Don't add a new router without it, and don't move
    `rate_limit_dep` onto individual handlers (we rely on it running once
    per request and stamping `X-RateLimit-`\* headers uniformly).
13. **API-key plaintext is never stored.** Only `sha256(plaintext)` goes
    into `api_keys.key_hash`. `mint_api_key()` returns the plaintext; the
    CLI prints it exactly once at issuance. Never log the plaintext and
    never read it back from the DB (it isn't there).
14. **MV refresh is a scraper responsibility, not the API's.** Scrapers
    call `refresh_price_mvs_if_needed` after `finish_scrape_run` commits
    (§3.6). The helper swallows errors on purpose — **don't** re-raise
    them; a flaky MV refresh must never fail-mask an otherwise successful
    scrape. If `CONCURRENTLY` is ever rejected (e.g. you added a 4th MV
    without a unique index), fix the index or pass `concurrently=False`
    manually via `pokeprice-api refresh-mvs --no-concurrently`. Don't
    stop using the hook.
15. **Every price MV must have a UNIQUE index.** Required for
    `REFRESH MATERIALIZED VIEW CONCURRENTLY`. Add the index in the same
    Alembic migration that creates the MV. 005 covers
    `mv_latest_price` + `mv_median_7d`; 006 covers `mv_cross_source_spread`.
16. **Use the official JP set abbreviation (the one printed on the card
    / used by `jp.pokellector.com` and SNKRDUNK), not a guess.** The ME
    era tripped this twice: Mega Brave is **M1L** (not `M1`) and Mega
    Symphonia is **M1S**. Setting `set_code: M1` made Cardrush work
    (Cardrush is lenient) but SNKRDUNK returned 0 rows on every card
    because its product numbers are `pkmn-tcg-M1L-NNN`. If a new set's
    SNKRDUNK run yields `succeeded=0 not_found=N`, **stop and probe the
    product-number namespace manually** before assuming SNKRDUNK just
    hasn't indexed it. The rename was destructive (drop + reseed +
    re-scrape) — cheap at 5839 rows, potentially expensive at 50k+.
    See also §4.2 for the M1 → M1L history.

---

## 7. Common commands

```bash
# Bring up infra
make up                      # postgres + minio
make migrate                 # alembic upgrade head

# Catalog (metadata pipeline)
make catalog-seed-sets                       # load data/sets/*.yml → sets
make catalog-bootstrap SET=SV2A              # Pokellector+TCGdex+Cardrush → data/cards/
make catalog-seed-cards                      # YML tree → artworks + cards
make catalog-seed-cards SET=SV2A             # single set
make catalog-verify                          # health snapshot

# Prices (scrapers auto-refresh the price MVs on completion)
make scrape-cardrush SET=SV2A                # one set
make scrape-cardrush ERA=SV                  # all sets in era
make scrape-snkrdunk ERA=SV

# API (read layer)
make api                                     # prod: 0.0.0.0:8000
make api-dev                                 # dev: 127.0.0.1:8000, reload

# API-key management (writes to the `api_keys` table)
uv run pokeprice-api create-key --owner dev@example.com --tier free
uv run pokeprice-api revoke-key pk_ab12cd
uv run pokeprice-api list-keys [--include-revoked]

# Manual MV refresh (only needed if the post-scrape hook failed or
# you imported data out-of-band)
uv run pokeprice-api refresh-mvs             # CONCURRENTLY (default)
uv run pokeprice-api refresh-mvs --no-concurrently  # fallback

# Dev loop
make test                                    # 163 tests
make lint
make format

# Manual inspection
uv run python -m pokeprice_catalog bootstrap-set --set SV2A --help
uv run python -m pokeprice_cardrush --set SV2A --rarity SAR --max-pages 1
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
