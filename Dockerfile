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

# Default: run the API
ENV PORT=8000
CMD ["uv", "run", "watari-api", "serve", "--host", "0.0.0.0", "--port", "8000"]
