"""Application settings via pydantic-settings, reads .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Infrastructure
    database_url: str = "postgresql+asyncpg://pokeprice:pokeprice@localhost:5433/pokeprice"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket_bronze: str = "pokeprice-bronze"
    aws_access_key_id: str = "pokeprice"
    aws_secret_access_key: str = "pokeprice123"
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

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+asyncpg", "+psycopg2")


settings = Settings()
