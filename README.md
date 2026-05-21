# Watari

Japanese Pokémon TCG price API and web UI. Fetches live listings from [Cardrush](https://www.cardrush-pokemon.jp/) and sold history from [SNKRDUNK](https://snkrdunk.com/) on demand, and cross-references international prices from [pokemontcg.io](https://pokemontcg.io/) (TCGPlayer USD) and [TCGdex EN](https://tcgdex.net/) (Cardmarket EUR). Covers **105 sets across SV, ME, CL, SWSH, and SM eras** (~12 000 card prints).

**Live API:** `https://watari-api.fly.dev`

---

## API

All endpoints are locale-prefixed. Currently `jp` is supported.

```
GET /healthz
GET /jp/sets
GET /jp/sets/{set_code}
GET /jp/sets/{set_code}/cards
GET /jp/cards/search
GET /jp/cards/batch
GET /jp/cards/by-sets
GET /jp/cards/{set_code}/{local_id}
GET /jp/cards/{set_code}/{local_id}/prices
GET /jp/cards/{set_code}/{local_id}/history
GET /jp/cards/{set_code}/{local_id}/spread
GET /jp/cards/{set_code}/{local_id}/market-price
GET /jp/cards/{set_code}/{local_id}/graded-prices
GET /jp/cards/{set_code}/{local_id}/graded-history
GET /jp/cards/{set_code}/{local_id}/international-prices
```

### Examples

```bash
# List all sets
curl https://watari-api.fly.dev/jp/sets

# Cards in a set
curl https://watari-api.fly.dev/jp/sets/SV2A/cards

# Latest price for a card (fetched live, cached 30 min)
curl "https://watari-api.fly.dev/jp/cards/SV2A/089/prices?variant=normal"
# → [{"card_id":"jp-sv2a-089-normal","source":"cardrush","condition":"A","price_jpy":50,...}]

# Cross-source price spread
curl "https://watari-api.fly.dev/jp/cards/SV2A/089/spread?variant=normal"

# Market price (Snkrdunk 7d median preferred, Cardrush floor fallback)
curl "https://watari-api.fly.dev/jp/cards/SV2A/089/market-price?variant=normal"

# Graded card history (PSA/BGS/CGC)
curl "https://watari-api.fly.dev/jp/cards/SV2A/089/graded-history?company=PSA&days=90"

# Ungraded price history (Snkrdunk sold comps, up to 90 days)
curl "https://watari-api.fly.dev/jp/cards/SV2A/089/history?variant=normal&days=30"

# International & reference prices (TCGPlayer USD + Cardmarket EUR)
curl "https://watari-api.fly.dev/jp/cards/SV2A/203/international-prices?variant=normal"
# → [{"market":"tcgplayer","condition_label":"Market","price_jpy":13175,"price_raw":85.64,"currency":"USD",...},...]
```

> **Note:** Price endpoints (`/prices`, `/spread`, `/market-price`, `/graded-*`, `/history`, `/international-prices`) fetch
> live from Cardrush, Snkrdunk, pokemontcg.io, and TCGdex EN. The first request per card may take 2–5 s;
> subsequent requests within 30 minutes are served from cache. `/history` returns Snkrdunk ungraded
> sold comps only (max 90 days). `/international-prices` returns `[]` for sets with no EN coverage.

### Rate limiting

All requests are rate-limited to **60 req/min** (free tier). Responses include
`X-RateLimit-Tier`, `X-RateLimit-Limit`, and `X-RateLimit-Remaining` headers.
Exceeded limits return HTTP 429 with a `Retry-After` header.

---

## Coverage

| Era | Sets | Notes |
|-----|------|-------|
| Scarlet & Violet (SV1S–SV11W) + SVP promos | 26 sets | — |
| Mask Expansion (M1L–M4) + MP promos | 7 sets | — |
| Pokémon Card Classic (CLF/CLL/CLK) | 3 sets | — |
| Sword & Shield (S1W–S12A) + SP promos | 31 sets | — |
| Sun & Moon (SM0–SM12A, SMP2) + SMPR promos | 38 sets | — |

Prices are fetched on demand from Cardrush (listings) and Snkrdunk (sold history).

---

## Stack

| Layer | Tech |
|-------|------|
| Language | Python 3.13, uv workspaces |
| API | FastAPI + uvicorn |
| Catalog | In-memory (`MemCatalog` from YAML) |
| Price fetching | `PriceProxy` — Cardrush + Snkrdunk (JP) + pokemontcg.io (TCGPlayer USD) + TCGdex EN (Cardmarket EUR); 30-min in-process cache |
| Rate limiting | In-memory token bucket (per process) |
| Frontend | Vite + React + TypeScript, Bun |
| Hosting | Fly.io (Singapore, `sin`) |
| CI/CD | GitHub Actions |

---

## Architecture

```
data/sets/*.yml + data/cards/{SET}/*.yml
          │
          ▼ (loaded at startup)
       MemCatalog (in-memory)
          │
          ▼
    FastAPI read layer
          │
    per-request (cache 30 min)
          │
    ┌─────┴──────┬──────────────┬─────────────┐
    ▼            ▼              ▼              ▼
Cardrush    Snkrdunk    pokemontcg.io    TCGdex EN
(listings)  (sold       (TCGPlayer USD)  (Cardmarket EUR)
             history)
```

The PostgreSQL schema, Alembic migrations, and scraper packages still exist and
can be re-enabled, but are not exercised in the current online-mode deployment.

---

## Local development

**Prerequisites:** [uv](https://docs.astral.sh/uv/), [Bun](https://bun.sh/) (frontend only)

No database setup required for the API.

```bash
# Run the API (dev mode with reload)
make api-dev

# Run tests
make test
```

### Frontend

```bash
make web-install          # bun install
make web-dev              # http://localhost:5173 (proxies to http://127.0.0.1:8000)
```

Copy `apps/web/.env.example` to `apps/web/.env.local` and set `VITE_API_BASE_URL`.

### Catalog pipeline (optional)

The in-memory catalog is loaded from the YAML files checked into the repo. To
bootstrap or update the catalog data:

```bash
# Bootstrap card data for a set (requires Pokellector/TCGCollector access)
make catalog-bootstrap SET=SV2A

# Run bootstrap tests
make test
```

### Running scrapers manually

Scrapers are not scheduled in CI but can be triggered via `workflow_dispatch`
or run locally (requires `.env` with Cardrush/Snkrdunk credentials):

```bash
make scrape-cardrush SET=SV2A
make scrape-snkrdunk ERA=sv2a
```

---

## Deployment

Deployed on [Fly.io](https://fly.io). No migrations or database provisioning
required for online mode.

```bash
# Deploy
fly deploy --remote-only

# View logs
fly logs -a watari-api
```

---

## Project structure

```
apps/
  web/               ← Vite + React frontend (Bun)
packages/
  core/              ← models, config, catalog helpers (DB layer kept for reference)
  catalog/           ← YML data tree + bootstrap/seed pipeline
    data/sets/       ← 105 set definitions (SV, ME, CL, SWSH, SM + promos)
    data/cards/      ← ~12 000 card YML files (source of truth)
  scraper_cardrush/  ← curl_cffi scraper (Cloudflare-bypass)
  scraper_snkrdunk/  ← sold-price scraper
  api/               ← FastAPI read layer (online mode)
    watari_api/
      catalog_mem.py ← MemCatalog (in-memory catalog from YAML)
      price_proxy.py ← PriceProxy (on-demand price fetching + cache)
migrations/          ← Alembic (head: 008_graded_price_points, inactive)
scripts/             ← set metadata generators, symbol sync, prod dump/bootstrap
.github/workflows/   ← deploy CI; scraper schedule disabled (workflow_dispatch only)
```
