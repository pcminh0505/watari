# Plan: Fly.io Deployment + Scheduled Scrapers

## Context

The project currently runs entirely on a local developer machine. The API (`watari-api`),
scrapers, and infra (Postgres, Redis, MinIO) all live in `docker-compose.yml`. There is no
Dockerfile, no deployment descriptor, no CI/CD, and the `packages/scheduler/` and
`packages/dispatcher/` packages are empty stubs.

This plan ships:
1. A single multi-stage **Dockerfile** for the monorepo (API + scrapers share one image).
2. A **Fly.io** deployment for the FastAPI read layer.
3. **Cloudflare R2** to replace MinIO in production (env-var swap only, no code changes).
4. **GitHub Actions cron** workflows to drive scheduled scraper runs via `fly machine run`
   (ephemeral Fly Machines, auto-destroy after completion — no always-on scheduler process).
5. **CI/CD** workflow: test → deploy API on push to `main`.
6. **Makefile** convenience targets for common prod ops.

What is NOT changing: scraper code, catalog/seed scripts, migration scripts, the
`packages/scheduler/` stub (platform cron replaces it), and local `docker-compose.yml`
dev workflow.

---

## Architecture

```
GitHub (main branch push)
  ├── CI: uv run pytest → fly deploy (API)
  └── Cron schedule
        ├── scrape-cardrush.yml  → fly machine run --command "python -m watari_cardrush --era SV/ME"
        └── scrape-snkrdunk.yml  → fly machine run --command "python -m watari_snkrdunk --era <set>"
                                    (matrix: 27 set codes, parallel)

Fly.io (region: nrt — Tokyo)
  ├── watari-api  (HTTP, auto-scale to 0 on idle)
  │     image: registry.fly.io/watari-api:latest
  │     cmd:   uv run watari-api serve --host 0.0.0.0 --port 8000
  ├── Fly Postgres  (fly pg create, managed)
  └── Fly Redis     (fly redis create, managed)

Cloudflare R2  (replaces MinIO; S3-compatible, env-var swap only)
```

---

## Files to Create / Modify

| File | Action | Purpose |
|------|--------|---------|
| `Dockerfile` | CREATE | Multi-stage uv build, shared by API + scrapers |
| `.dockerignore` | CREATE | Exclude dev artifacts, tests, dumps |
| `fly.toml` | CREATE | Fly.io app config for API |
| `.github/workflows/deploy.yml` | CREATE | Test + deploy on push to main |
| `.github/workflows/scrape.yml` | CREATE | Scheduled scraper runs |
| `Makefile` | MODIFY | Add `deploy`, `logs`, `ssh`, `migrate-prod` targets |

---

## Phase 1: Dockerfile

Single multi-stage build. `uv` is installed from the official dist image. All workspace
packages are installed in one `RUN uv sync` step. Default CMD runs the API; scrapers are
invoked by overriding the command at runtime.

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Install dependencies first (cache-friendly)
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
RUN uv sync --all-packages --no-dev --frozen

# Default: run the API
ENV PORT=8000
CMD ["uv", "run", "watari-api", "serve", "--host", "0.0.0.0", "--port", "8000"]
```

**Key decisions:**
- `--frozen` ensures exact lockfile is used (no silent upgrades).
- `--no-dev` omits ruff, mypy, vulture, pytest from the prod image.
- `packages/catalog/data/` is included (YMLs are small; needed for catalog seed runs,
  but catalog seeding is run from local machine pointing at prod DB, not from this image).
- No `EXPOSE` directive needed — Fly.io reads the HTTP service port from `fly.toml`.

### .dockerignore

```
.git/
.env
*.env
__pycache__/
**/__pycache__/
**/*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/
dumps/
.reports/
plans/
tests/
.venv/
```

---

## Phase 2: fly.toml

```toml
app = "watari-api"
primary_region = "nrt"

[build]
dockerfile = "Dockerfile"

[deploy]
# Run migrations before the new version receives traffic.
release_command = "uv run alembic upgrade head"

[http_service]
internal_port    = 8000
force_https      = true
auto_stop_machines  = "stop"
auto_start_machines = true
min_machines_running = 0   # scale to 0 on idle — cheapest tier

[[vm]]
memory   = "512mb"
cpu_kind = "shared"
cpus     = 1
```

**Secrets to set via `fly secrets set`** (run once, never committed):
```
DATABASE_URL              postgresql+asyncpg://...  (fly pg attach output)
REDIS_URL                 rediss://...              (fly redis attach output)
S3_ENDPOINT_URL           https://<acct>.r2.cloudflarestorage.com
S3_BUCKET_BRONZE          watari-bronze
AWS_ACCESS_KEY_ID         <r2-access-key>
AWS_SECRET_ACCESS_KEY     <r2-secret-key>
AWS_REGION                auto
SNKRDUNK_COOKIES          <cookie-string>           (verify env var name in client.py first)
CARDRUSH_PROXY_URL        <proxy-url>               (optional; only if Fly IPs get blocked)
API_CORS_ORIGINS          https://your-frontend.com
SENTRY_DSN                <dsn>                     (optional)
LOG_LEVEL                 INFO
```

> **Risk:** Cardrush uses Cloudflare TLS fingerprint blocking. Fly.io datacenter IPs
> may be blocked on first run. If `scrape-cardrush` returns 0 rows or 403s, set
> `CARDRUSH_PROXY_URL` to a residential proxy.

---

## Phase 3: Cloudflare R2

No code changes required — boto3 uses the S3 endpoint URL. Steps (done manually once):

1. In Cloudflare dashboard → R2 → Create bucket `watari-bronze` (region: Auto).
2. R2 → Manage R2 API Tokens → Create token (Object Read & Write on `watari-bronze`).
3. Note: Account ID, Access Key ID, Secret Access Key.
4. `fly secrets set S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com ...`
5. Local `.env` keeps pointing to MinIO (`http://localhost:9000`) — dev workflow unchanged.

---

## Phase 4: Initial Production Bootstrap

Run once from local machine (mirrors existing `scripts/prod_bootstrap.sh` pattern):

```bash
# 1. Create Fly infra
fly apps create watari-api
fly pg create --name watari-pg --region nrt --vm-size shared-cpu-1x
fly pg attach watari-pg --app watari-api   # sets DATABASE_URL secret
fly redis create --name watari-redis --region nrt
fly redis attach watari-redis --app watari-api  # sets REDIS_URL secret

# 2. Set remaining secrets (R2, SNKRDUNK, etc.)
fly secrets set S3_ENDPOINT_URL=... AWS_ACCESS_KEY_ID=... ...

# 3. First deploy (runs release_command = alembic upgrade head)
fly deploy

# 4. Seed catalog via fly proxy tunnel
fly proxy 5434:5432 -a watari-pg &          # tunnel local 5434 → prod postgres
DATABASE_URL="postgresql+asyncpg://watari:...@localhost:5434/watari" \
  uv run python -m watari_catalog seed-sets
DATABASE_URL="postgresql+asyncpg://watari:...@localhost:5434/watari" \
  uv run python -m watari_catalog seed-cards

# 5. Optional: import existing price dump
fly proxy 5434:5432 -a watari-pg &
gunzip -c dumps/watari-data-<UTC>.sql.gz | psql "postgresql://watari:...@localhost:5434/watari"

# 6. Refresh materialized views
fly ssh console -a watari-api -C "uv run watari-api refresh-mvs"
```

---

## Phase 5: Scheduled Scrapers — `.github/workflows/scrape.yml`

Two jobs in one workflow file. Both use `fly machine run` to create an ephemeral machine
from the deployed image; machine auto-destroys on exit.

```yaml
name: Scheduled scrapers
on:
  schedule:
    # Cardrush: 09:00 + 17:00 JST (= 00:00 + 08:00 UTC)
    - cron: "0 0,8 * * *"
    # SNKRDUNK: 03:00 JST (= 18:00 UTC previous day)
    - cron: "0 18 * * *"
  workflow_dispatch:
    inputs:
      job:
        description: "cardrush-sv | cardrush-me | snkrdunk"
        required: true

jobs:
  cardrush-sv:
    # Runs at 00:00 UTC and 08:00 UTC, or on manual dispatch
    if: >
      (github.event_name == 'schedule' && (
        contains(github.event.schedule, '0 0,8') )) ||
      (github.event_name == 'workflow_dispatch' && inputs.job == 'cardrush-sv')
    runs-on: ubuntu-latest
    steps:
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - run: |
          fly machine run registry.fly.io/watari-api:latest \
            --app watari-api \
            --command "uv run python -m watari_cardrush --era SV" \
            --auto-destroy \
            --vm-size shared-cpu-2x \
            --region nrt \
            --wait-timeout 1800
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}

  cardrush-me:
    # Runs at 08:00 UTC daily (piggybacks on the 17:00 JST run)
    if: >
      (github.event_name == 'schedule' && contains(github.event.schedule, '0 0,8') ) ||
      (github.event_name == 'workflow_dispatch' && inputs.job == 'cardrush-me')
    runs-on: ubuntu-latest
    steps:
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - run: |
          fly machine run registry.fly.io/watari-api:latest \
            --app watari-api \
            --command "uv run python -m watari_cardrush --era ME" \
            --auto-destroy \
            --vm-size shared-cpu-2x \
            --region nrt \
            --wait-timeout 1800
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}

  snkrdunk:
    # Runs nightly at 18:00 UTC (03:00 JST)
    if: >
      (github.event_name == 'schedule' && contains(github.event.schedule, '0 18') ) ||
      (github.event_name == 'workflow_dispatch' && inputs.job == 'snkrdunk')
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false   # one set failing doesn't cancel others
      max-parallel: 5    # limit concurrent fly machines
      matrix:
        era:
          # 27 sets: all except SV1 (merged into sv1v on SNKRDUNK)
          - sv1v
          - sv2
          - sv2a
          - sv3
          - sv3pt5
          - sv4
          - sv4pt5
          - sv5
          - sv6
          - sv6a
          - sv7
          - sv7a
          - sv8
          - sv8a
          - sv9
          - sv9ex
          - sv10
          - sv10a
          - sv11b
          - sv11w
          - sv12
          - m1l
          - m1s
          - m2
          - m2a
    steps:
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - run: |
          fly machine run registry.fly.io/watari-api:latest \
            --app watari-api \
            --command "uv run python -m watari_snkrdunk --era ${{ matrix.era }}" \
            --auto-destroy \
            --vm-size shared-cpu-1x \
            --region nrt \
            --wait-timeout 600
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

**GitHub Secrets to configure** (Settings → Secrets → Actions):
- `FLY_API_TOKEN` — from `fly auth token`

---

## Phase 6: CI/CD — `.github/workflows/deploy.yml`

```yaml
name: Test and deploy
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          python-version: "3.13"
      - run: uv sync --all-packages --frozen
      - run: uv run pytest

  deploy:
    needs: test
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - run: fly deploy --remote-only
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

---

## Phase 7: Makefile Additions

```makefile
# ── Production ops ──────────────────────────────────────────
deploy:
	fly deploy --remote-only

deploy-dry:
	fly deploy --dry-run

migrate-prod:
	fly ssh console -a watari-api -C "uv run alembic upgrade head"

refresh-mvs-prod:
	fly ssh console -a watari-api -C "uv run watari-api refresh-mvs"

logs:
	fly logs -a watari-api

ssh:
	fly ssh console -a watari-api

scale-up:
	fly scale count 1 -a watari-api

scale-down:
	fly scale count 0 -a watari-api
```

---

## Verification

### After initial deployment
```bash
curl https://watari-api.fly.dev/healthz                          # {"status":"ok"}
curl https://watari-api.fly.dev/jp/sets?limit=5                  # 5 sets
curl https://watari-api.fly.dev/jp/cards/SV2A/089/prices         # prices for Muk
```

### After first scraper run
1. Check GitHub Actions run → green for all matrix jobs
2. `fly logs -a watari-api` — check for scrape completion messages
3. `curl .../jp/cards/SV2A/001/prices` — fresh price_points present
4. `curl .../jp/cards/SV2A/001/spread` — MV refreshed

### Tests (unchanged, run locally)
```bash
make test    # 176 passed
```

---

## SNKRDUNK Era List Note

The matrix currently has 25 entries. Cross-check against DB with:
```bash
fly ssh console -a watari-api -C \
  "uv run python -c \"from watari_core.db import sync_engine; ...\""
```
Or query locally: `SELECT set_code, era_block FROM sets WHERE language='jp' ORDER BY set_code;`
and add any missing set codes to the matrix. SV12 / newer sets should be added as they're
bootstrapped.

---

## Known Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Fly IPs blocked by Cardrush/Cloudflare | Medium | Set `CARDRUSH_PROXY_URL` to residential proxy |
| SNKRDUNK cookie expiry | High | Re-run `fly secrets set SNKRDUNK_COOKIES=...` when cookies rotate; add to runbook |
| asyncpg 32767 arg limit on popular cards | Low | Already documented; batch inserts fix (pending §5.1) |
| Cold-start latency on idle API (scale-to-0) | Low | First request wakes machine in ~2s; acceptable for this use case |
| `fly machine run` image tag drift | Low | Workflow uses `:latest` which always reflects the last `fly deploy` |
