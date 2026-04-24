"""Application settings via pydantic-settings, reads .env."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Infrastructure
    database_url: str = "postgresql+asyncpg://watari:watari@localhost:5433/watari"

    @field_validator("database_url", mode="before")
    @classmethod
    def normalise_database_url(cls, v: str) -> str:
        # Rewrite scheme: postgres:// / postgresql:// → postgresql+asyncpg://
        # Fly pg attach and external providers (Neon, Supabase) all emit bare URLs.
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+asyncpg://", 1)
        elif v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        # asyncpg uses ?ssl=require; psycopg2-style ?sslmode=require is not understood.
        v = v.replace("sslmode=", "ssl=")
        return v

    redis_url: str = "redis://localhost:6379/0"
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
    api_cors_origins: str = "http://localhost:3000"
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
