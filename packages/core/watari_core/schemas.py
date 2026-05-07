"""Pydantic DTOs for the new catalog + price point shape."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class SetBase(BaseModel):
    set_code: str
    era_block: str
    language: str = "jp"
    name_ja: str | None = None
    name_en: str | None = None
    release_date: date | None = None
    total: int | None = None
    total_value_jpy: int | None = None
    parent_set_code: str | None = None
    tcgdex_id: str | None = None
    source_refs: dict[str, Any] = {}


class SetOut(SetBase):
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ArtworkBase(BaseModel):
    artwork_id: str
    set_code: str
    local_id: str
    name_ja: str | None = None
    name_en: str | None = None
    rarity_code: str | None = None
    image_url: str | None = None
    category: str = "card"
    illustrator: str | None = None
    source_refs: dict[str, Any] = {}


class CardBase(BaseModel):
    card_id: str
    artwork_id: str
    set_code: str
    local_id: str
    variant: str = "normal"
    is_tracked: bool = True
    source_refs: dict[str, Any] = {}


class CardOut(CardBase):
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PricePointBase(BaseModel):
    card_id: str
    source: str
    source_type: str
    condition: str
    price_jpy: int
    stock_qty: int | None = None
    observed_at: datetime
    external_url: str | None = None
    scrape_run_id: int | None = None


class PricePointOut(PricePointBase):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class GradedPricePointCreate(BaseModel):
    card_id: str
    source: str
    source_type: str
    grade_company: str
    grade_score: float
    price_jpy: int
    stock_qty: int | None = None
    observed_at: datetime
    external_url: str | None = None
    scrape_run_id: int | None = None
