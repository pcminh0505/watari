"""ORM models.

Catalog:
    - ``Set``: one row per printed expansion.
    - ``Artwork``: one row per (set, local_id). Owns image, names, rarity.
    - ``Card``: one row per (set, local_id, variant). References Artwork.
      "Card" here is a *print* — a specific variant of an artwork that can be
      priced independently (normal, master_ball_mirror, poke_ball_mirror, …).

Downstream (wiped on migration, same shape as before):
    - ``ScrapeRun``, ``CardScrapeState``, ``PricePoint``, ``ApiKey``.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from watari_core.conditions import Condition
from watari_core.db import Base

# Re-export for backwards compatibility. ``ConditionEnum`` is the historical
# name; ``Condition`` is the canonical one (defined in ``conditions``).
ConditionEnum = Condition


# --- Enums ---------------------------------------------------------------


class SourceEnum(StrEnum):
    cardrush = "cardrush"
    snkrdunk = "snkrdunk"


class SourceTypeEnum(StrEnum):
    listing = "listing"
    sold = "sold"


# --- Catalog tables ------------------------------------------------------


class Set(Base):
    """One row per printed set (expansion, high-class pack, starter deck, etc.)."""

    __tablename__ = "sets"

    set_code: Mapped[str] = mapped_column(Text, primary_key=True)
    era_block: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default="jp")
    name_ja: Mapped[str | None] = mapped_column(Text)
    name_en: Mapped[str | None] = mapped_column(Text)
    release_date: Mapped[date | None] = mapped_column(Date)
    total: Mapped[int | None] = mapped_column(Integer)
    parent_set_code: Mapped[str | None] = mapped_column(
        Text, ForeignKey("sets.set_code")
    )
    tcgdex_id: Mapped[str | None] = mapped_column(Text)
    source_refs: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_sets_era_block", "era_block"),
        Index("idx_sets_release_date", release_date.desc()),
    )


class Artwork(Base):
    """One row per (set_code, local_id). Owns artwork-level metadata.

    Image, names, rarity and illustrator live here exactly once and are
    shared by every variant print (normal, master_ball_mirror, …).
    """

    __tablename__ = "artworks"

    artwork_id: Mapped[str] = mapped_column(Text, primary_key=True)
    set_code: Mapped[str] = mapped_column(
        Text, ForeignKey("sets.set_code"), nullable=False
    )
    local_id: Mapped[str] = mapped_column(Text, nullable=False)
    name_ja: Mapped[str | None] = mapped_column(Text)
    name_en: Mapped[str | None] = mapped_column(Text)
    rarity_code: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="card"
    )
    illustrator: Mapped[str | None] = mapped_column(Text)
    source_refs: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "uq_artworks_set_local",
            "set_code",
            "local_id",
            unique=True,
        ),
        Index("idx_artworks_set_code", "set_code"),
        Index("idx_artworks_rarity_code", "rarity_code"),
    )


class Card(Base):
    """One row per (set_code, local_id, variant) = one price-discovery print.

    All human-facing metadata (image, names, rarity) is on the parent
    ``Artwork`` row. This table exists to be the foreign-key target of
    ``price_points`` / ``card_scrape_state`` and to enumerate which
    variants exist for each artwork.
    """

    __tablename__ = "cards"

    card_id: Mapped[str] = mapped_column(Text, primary_key=True)
    artwork_id: Mapped[str] = mapped_column(
        Text, ForeignKey("artworks.artwork_id"), nullable=False
    )
    set_code: Mapped[str] = mapped_column(
        Text, ForeignKey("sets.set_code"), nullable=False
    )
    local_id: Mapped[str] = mapped_column(Text, nullable=False)
    variant: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="normal"
    )
    is_tracked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    source_refs: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "uq_cards_set_local_variant",
            "set_code",
            "local_id",
            "variant",
            unique=True,
        ),
        Index("idx_cards_artwork_id", "artwork_id"),
        Index("idx_cards_set_code", "set_code"),
        Index(
            "idx_cards_is_tracked",
            "is_tracked",
            postgresql_where=(is_tracked == True),  # noqa: E712
        ),
    )


# --- Scrape / price tables (unchanged shape) -----------------------------


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="running")
    cards_attempted: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cards_succeeded: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_summary: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

    __table_args__ = (Index("idx_scrape_runs_source_started", "source", started_at.desc()),)


class CardScrapeState(Base):
    __tablename__ = "card_scrape_state"

    card_id: Mapped[str] = mapped_column(
        Text, ForeignKey("cards.card_id"), primary_key=True
    )
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )


class PricePoint(Base):
    __tablename__ = "price_points"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    card_id: Mapped[str] = mapped_column(
        Text, ForeignKey("cards.card_id"), nullable=False
    )
    source: Mapped[SourceEnum] = mapped_column(
        Enum(SourceEnum, name="source_enum", create_constraint=True, native_enum=True),
        nullable=False,
    )
    source_type: Mapped[SourceTypeEnum] = mapped_column(
        Enum(
            SourceTypeEnum,
            name="source_type_enum",
            create_constraint=True,
            native_enum=True,
        ),
        nullable=False,
    )
    condition: Mapped[Condition] = mapped_column(
        Enum(
            Condition,
            name="condition_enum",
            create_constraint=True,
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    price_jpy: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_qty: Mapped[int | None] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    external_url: Mapped[str | None] = mapped_column(Text)
    scrape_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("scrape_runs.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "uq_price_points_idem",
            "card_id",
            "source",
            "source_type",
            "condition",
            "price_jpy",
            "observed_at",
            func.coalesce(external_url, ""),
            unique=True,
        ),
        Index(
            "idx_price_points_card_cond_time",
            "card_id",
            "condition",
            observed_at.desc(),
        ),
    )


class GradedPricePoint(Base):
    """One row per graded (PSA/BGS/CGC) card listing observation.

    Kept separate from ``price_points`` so the four existing materialized views
    are not touched.  Grade company and score are stored as plain text / numeric
    rather than enums so new grades can be added without a schema migration.
    """

    __tablename__ = "graded_price_points"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    card_id: Mapped[str] = mapped_column(
        Text, ForeignKey("cards.card_id"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    grade_company: Mapped[str] = mapped_column(Text, nullable=False)
    grade_score: Mapped[float] = mapped_column(Numeric(3, 1), nullable=False)
    price_jpy: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_qty: Mapped[int | None] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    external_url: Mapped[str | None] = mapped_column(Text)
    scrape_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("scrape_runs.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "uq_graded_price_points_idem",
            "card_id",
            "source",
            "grade_company",
            "grade_score",
            "price_jpy",
            "observed_at",
            func.coalesce(external_url, ""),
            unique=True,
        ),
        Index(
            "idx_graded_price_points_card_grade_time",
            "card_id",
            "grade_company",
            "grade_score",
            observed_at.desc(),
        ),
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    owner_email: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str] = mapped_column(Text, nullable=False, server_default="free")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
