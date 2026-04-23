# CLAUDE.md — Project State & Roadmap

> **Purpose:** this file is the handoff note for the next Claude session.
> It captures "what the codebase is", "what just landed", "what's next",
> and the handful of invariants that are easy to break.
> Update it whenever the architecture changes — especially after a
> destructive migration, a new source, or a schema split.
>
> Last updated: 2026-04-23 (Catalog v3 + API v1 + auth/rate-limit + post-scrape MV refresh hook).

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

### 4.1 End-to-end smoke (last run 2026-04-23)

| Step                                               | Result                                                                                         |
| -------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `alembic upgrade head`                             | clean (head = `006_mv_spread_unique_index`)                                                    |
| `make catalog-seed-sets`                           | 28 sets upserted                                                                               |
| `make catalog-bootstrap SET={SV2A,M2A}`            | SV2A: 210 YMLs (3 variants) · M2A: 250 YMLs (1 variant)                                        |
| `make catalog-seed-cards`                          | SV2A: 210 artworks / 516 prints · M2A: 250 / 250                                               |
| `make catalog-verify`                              | 0 orphans · 0 artworks missing rarity/img · 128 missing JA (all M2A Commons)                   |
| `make scrape-cardrush ERA=sv,me`                   | SV2A 1319 rows (516 cards) · M2A 264 rows (86 cards)                                           |
| `make scrape-snkrdunk ERA=sv2a`                    | run 6: 516/516 cards, 6546 rows written                                                        |
| `make scrape-snkrdunk ERA=m2a`                     | run 7: 249/250 cards (1 failed: asyncpg 32767 arg limit on a mega-history card), 17647 rows    |
| `pokeprice-api refresh-mvs` (CONCURRENTLY)         | mv_latest_price 1824 · mv_median_7d 141 · mv_cross_source_spread 40                            |
| `uv run pytest`                                    | **163 passed** (156 prior + 5 mvs + 2 cli refresh-mvs)                                         |
| `uv run python -c "from pokeprice_api import app"` | app imports, 12 routes registered; `/healthz` has no deps, other routes carry `rate_limit_dep` |

### 4.2 Data that's already committed

- `data/sets/*.yml` — all 28 SV + ME sets we care about, with `pokellector_slug`
  filled for the 2 we've bootstrapped (SV2A, M2A). The rest have `pokellector_slug: null`.
- `data/cards/SV2A/*.yml` — 210 files, full coverage.
- `data/cards/M2A/*.yml` — 250 files, full metadata except 128 JA names.

### 4.3 Price data in the DB (post-smoke snapshot)

| Source     | SV2A                 | M2A                    |
| ---------- | -------------------- | ---------------------- |
| Cardrush   | 1319 rows / 516 cards | 264 rows / 86 cards    |
| SNKRDUNK   | 6546 rows / 516 cards | 17647 rows / 249 cards |
| Total `price_points` | ~25.8k                                        |

MVs now populated (see §4.1), so `/cards/{id}/prices` and
`/cards/{id}/spread` return real data for SV2A and M2A.

---

## 5. Pending / roadmap (in priority order)

### 5.1 Immediate follow-ups (next session can pick up directly)

1. **Bootstrap the remaining 26 sets.**

- Fill `pokellector_slug` in each `data/sets/{SET}.yml`
  (slug = URL path after `https://jp.pokellector.com/`, e.g. `Scarlet-ex-Expansion`).
- Run `make catalog-bootstrap SET=<code>` per set. It's ~1–2 min per set.
- Then `make catalog-seed-cards` once.
- Commit the generated YMLs in batches per era block for reviewable diffs.

2. **Backfill missing `name_ja` for M2A Commons.**

- Option A (preferred): wait for Cardrush to list Commons, re-bootstrap.
- Option B: hand-fill from scans / the official tracker page, with `# manual: true`.
- Option C: add SNKRDUNK as a third name_ja source (heavier: needs cookie auth).

3. **Backfill price data for the new sets as they're bootstrapped.**

- After `catalog-bootstrap` + `catalog-seed-cards` for a new set, run
  `make scrape-cardrush SET=<code>` and `make scrape-snkrdunk ERA=<code>`
  to prime `price_points`. The post-scrape hook (§3.6) now handles MV
  refresh automatically — you don't need a manual step.
- **Known gotcha:** SNKRDUNK for mega-popular cards can trip the asyncpg
  32767-query-arg limit when writing a card's full history in one insert
  (one M2A card hit this on run 7). Low-priority fix: batch
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
