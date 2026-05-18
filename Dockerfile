# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Install dependencies first (cache-friendly layer)
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
RUN uv sync --all-packages --no-dev --frozen

COPY alembic.ini ./
COPY migrations/ migrations/

# Pre-compile YAML catalog → single pickle for fast startup.
# Reading 10 000+ YAML files at runtime on a shared-CPU VM takes 2+ minutes;
# pickle.loads() of the same data takes < 1 s.
RUN /app/.venv/bin/python - <<'EOF'
import concurrent.futures, pickle, yaml
from pathlib import Path
from watari_catalog.paths import cards_dir, data_dir
from watari_catalog.seed_sets import load_sets_yaml

sets_raw = load_sets_yaml()
cards_base = cards_dir()

card_files = [
    (p, d.name.upper())
    for d in sorted(cards_base.iterdir()) if d.is_dir()
    for p in sorted(d.glob("*.yml"))
]

def _read(path):
    try:
        r = yaml.safe_load(path.read_text("utf-8"))
        return r if isinstance(r, dict) else None
    except Exception:
        return None

with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    raws = list(pool.map(_read, [p for p, _ in card_files]))

cards = [
    (sc, p.stem, r)
    for (p, sc), r in zip(card_files, raws)
    if r is not None
]

cache_path = data_dir() / ".catalog_cache.pkl"
cache_path.write_bytes(pickle.dumps({"sets": sets_raw, "cards": cards}, protocol=5))
print(f"Catalog cache: {len(sets_raw)} sets, {len(cards)} cards → {cache_path.stat().st_size // 1024} KB")
EOF

# Default: run the API
ENV PORT=8000
CMD ["/app/.venv/bin/watari-api", "serve", "--host", "0.0.0.0", "--port", "8000"]
