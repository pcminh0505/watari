# Watari

Japanese Pokémon TCG price API. Scrapes live listings from [Cardrush](https://www.cardrush-pokemon.jp/) and sold history from [SNKRDUNK](https://snkrdunk.com/), normalises them into a unified schema, and exposes a read-only REST API — covering all **28 SV + ME era sets** (~4,500 prints, 117k+ price points).

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

| Era | Sets | Sources |
|-----|------|---------|
| Scarlet & Violet (SV1–SV12) | 23 sets | Cardrush + SNKRDUNK |
| Mask Expansion (M1L–M2A) | 5 sets | Cardrush + SNKRDUNK |

Scrapers run on a schedule via Fly.io ephemeral machines:
- **Cardrush** — twice daily (00:00 + 08:00 UTC)
- **SNKRDUNK** — nightly (18:00 UTC)

---

## Stack

| Layer | Tech |
|-------|------|
| Language | Python 3.13, uv workspaces |
| API | FastAPI + uvicorn |
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

**Prerequisites:** Docker, [uv](https://docs.astral.sh/uv/)

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

### Scraping locally

```bash
# Single set
make scrape-cardrush SET=SV2A
make scrape-snkrdunk ERA=sv2a

# Full era
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
packages/
  core/              ← models, config, DB session, catalog helpers
  catalog/           ← YML data tree + bootstrap/seed pipeline
    data/sets/       ← 28 set definitions
    data/cards/      ← ~4,000 card YML files (source of truth)
  scraper_cardrush/  ← curl_cffi scraper (Cloudflare-bypass)
  scraper_snkrdunk/  ← sold-price scraper
  api/               ← FastAPI read layer
migrations/          ← Alembic (head: 006)
.github/workflows/   ← deploy + scheduled scraper CI
```
