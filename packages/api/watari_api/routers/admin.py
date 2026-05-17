"""Admin endpoints — stubbed out in online mode (no scrape-run history)."""

from __future__ import annotations

from fastapi import APIRouter

from watari_api.schemas import ScrapeHealthRow

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/scrape-health", response_model=list[ScrapeHealthRow])
async def scrape_health() -> list[ScrapeHealthRow]:
    """Returns empty list in online mode — no scrape history without a database."""
    return []
