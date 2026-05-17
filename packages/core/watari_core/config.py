"""Application settings via pydantic-settings, reads .env."""

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Infrastructure
    database_url: str = "postgresql+asyncpg://watari:watari@localhost:5432/watari"

    @field_validator("database_url", mode="before")
    @classmethod
    def normalise_database_url(cls, v: str) -> str:
        # Rewrite scheme: postgres:// / postgresql:// → postgresql+asyncpg://
        # Fly pg attach and external providers (Neon, Supabase) all emit bare URLs.
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+asyncpg://", 1)
        elif v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        # Strip ssl/sslmode from the URL query string.
        # Passing ssl= in the URL causes SQLAlchemy 2.0 to inject a
        # `channel_binding` kwarg that asyncpg's connect() does not accept.
        # SSL is handled in db.py via connect_args instead.
        parsed = urlparse(v)
        clean_params = {
            k: vals
            for k, vals in parse_qs(parsed.query, keep_blank_values=True).items()
            if k not in ("ssl", "sslmode", "channel_binding")
        }
        new_query = urlencode({k: vals[0] for k, vals in clean_params.items()})
        return urlunparse(parsed._replace(query=new_query))

    redis_url: str = ""  # empty = memory-only; set REDIS_URL env var to enable L2 cache
    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket_bronze: str = "watari-bronze"
    aws_access_key_id: str = "watari"
    aws_secret_access_key: str = "watari123"
    aws_region: str = "us-east-1"

    # Scrapers
    cardrush_proxy_url: str = ""
    scraper_jitter_min_sec: float = 2.0
    scraper_jitter_max_sec: float = 4.0
    scraper_batch_size: int = 20

    # API
    api_cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"
    sentry_dsn: str = ""

    # API auth + rate limiting
    # Header used to carry the raw API key; case-insensitive per RFC 7230.
    api_key_header: str = "X-API-Key"
    # Per-tier token-bucket: "tier:capacity:refill_per_sec". Comma-separated.
    # capacity = max burst, refill = sustained rate. A minute-ish view:
    #   60:1.0  ≈ 60 req burst, 60 req/min sustained.
    # 'free' MUST be present (anonymous + fallback tier).
    api_rate_limits: str = "free:60:1.0,paid:600:10.0,admin:6000:100.0"


settings = Settings()
