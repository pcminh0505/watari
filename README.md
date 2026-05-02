# Watari

Japanese Pokémon TCG price API and web UI. Scrapes live listings from [Cardrush](https://www.cardrush-pokemon.jp/) and sold history from [SNKRDUNK](https://snkrdunk.com/), normalises them into a unified schema, and exposes a read-only REST API — covering **98 sets across SV, ME, SWSH, and SM eras** (~10 800 card prints).

**Live API:** `https://watari-api.fly.dev`

---

## API

All endpoints are locale-prefixed. Currently `jp` is supported.

```
GET /healthz
GET /jp/sets
GET /jp/sets/{set_code}
GET /jp/sets/{set_code}/cards
GET /jp/cards/{set_code}/{local_id}
GET /jp/cards/{set_code}/{local_id}/prices
GET /jp/cards/{set_code}/{local_id}/history
GET /jp/cards/{set_code}/{local_id}/spread
```

### Examples

```bash
# List all sets
curl https://watari-api.fly.dev/jp/sets

# Cards in a set
curl https://watari-api.fly.dev/jp/sets/SV2A/cards

# Latest price for a card
curl "https://watari-api.fly.dev/jp/cards/SV2A/089/prices?variant=normal"
# → [{"card_id":"jp-sv2a-089-normal","source":"cardrush","condition":"A","price_jpy":50,...}]

# Cross-source price spread
curl "https://watari-api.fly.dev/jp/cards/SV2A/089/spread?variant=normal"

# Price history
curl "https://watari-api.fly.dev/jp/cards/SV2A/089/history?variant=normal&days=30"
```

### Authentication

Requests without an API key are rate-limited to **60 req/min** (free tier). Pass a key via header:

```
X-API-Key: your_key_here
```

---

## Coverage

| Era | Sets | Scrape schedule |
|-----|------|-----------------|
| Scarlet & Violet (SV1S–SV11) | 25 sets | Cardrush 2×/day · SNKRDUNK nightly |
| Mask Expansion (M1L–M4) | 6 sets | Cardrush 2×/day · SNKRDUNK nightly |
| Sword & Shield (S1W–S12A) | 30 sets | Cardrush + SNKRDUNK weekly (Sun 06:00 JST) |
| Sun & Moon (SM0–SM12A, SMP2) | 37 sets | Cardrush + SNKRDUNK weekly (Sun 06:00 JST) |

Scrapers run via Fly.io ephemeral machines triggered by GitHub Actions.

---

## Stack

| Layer | Tech |
|-------|------|
| Language | Python 3.13, uv workspaces |
| API | FastAPI + uvicorn |
| Frontend | Vite + React + TypeScript, Bun |
| Database | PostgreSQL 17 (Neon serverless) |
| Cache / rate-limit | Redis (Upstash) |
| Object storage | Cloudflare R2 (bronze layer) |
| Hosting | Fly.io (Singapore, `sin`) |
| CI/CD | GitHub Actions |

---

## Architecture

```
Pokellector + TCGdex + Cardrush
        │
        ▼
  bootstrap-set → data/cards/{SET}/*.yml   ← git-versioned card metadata
        │
        ▼
   seed-cards → artworks + cards tables
        │
  cardrush-scrape ──┐
  snkrdunk-scrape ──┼──→ price_points + R2 bronze
                    │
                    ▼
          refresh materialized views
          (mv_latest_price, mv_median_7d,
           mv_cross_source_spread)
                    │
                    ▼
              FastAPI read layer
```

---

## Local development

**Prerequisites:** Docker, [uv](https://docs.astral.sh/uv/), [Bun](https://bun.sh/) (frontend only)

```bash
# Start Postgres + MinIO
make up

# Run migrations
make migrate

# Seed catalog (sets + cards)
make catalog-seed-sets
make catalog-seed-cards

# Run the API (dev mode with reload)
make api-dev

# Run tests
make test
```

Copy `.env.example` to `.env` and adjust credentials as needed.

### Frontend

```bash
make web-install          # bun install
make web-dev              # http://localhost:5173 (proxies to http://127.0.0.1:8000)
```

Copy `apps/web/.env.example` to `apps/web/.env.local` and set `VITE_API_BASE_URL`.

### Scraping locally

```bash
# Single set
make scrape-cardrush SET=SV2A
make scrape-snkrdunk ERA=sv2a

# Full era (SV | ME | SM | SW)
make scrape-cardrush ERA=SV
make scrape-snkrdunk ERA=ME
```

---

## Deployment

Deployed on [Fly.io](https://fly.io). Migrations run automatically on each deploy via an ephemeral machine.

```bash
# Deploy
fly deploy --remote-only

# Run scrapers manually on Fly
IMAGE=$(fly image show --app watari-api --json | python3 -c \
  "import sys,json; d=json.load(sys.stdin)[0]; print(d['Registry']+'/'+d['Repository']+':'+d['Tag'])")

fly machine run "$IMAGE" \
  --app watari-api --name scraper-cardrush-sv --rm \
  --vm-size shared-cpu-2x --region sin \
  -- uv run python -m watari_cardrush --era SV

# Issue an API key
uv run watari-api create-key --owner you@example.com --tier free
```

---

## Project structure

```
apps/
  web/               ← Vite + React frontend (Bun)
packages/
  core/              ← models, config, DB session, catalog helpers
  catalog/           ← YML data tree + bootstrap/seed pipeline
    data/sets/       ← 98 set definitions (SV, ME, SWSH, SM)
    data/cards/      ← ~10 800 card YML files (source of truth)
  scraper_cardrush/  ← curl_cffi scraper (Cloudflare-bypass)
  scraper_snkrdunk/  ← sold-price scraper
  api/               ← FastAPI read layer
migrations/          ← Alembic (head: 006)
scripts/             ← set metadata generators, symbol sync, prod dump/bootstrap
.github/workflows/   ← deploy + scheduled scraper CI (daily SV/ME, weekly SM/SW)
```
