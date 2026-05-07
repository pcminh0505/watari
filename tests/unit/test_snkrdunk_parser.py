"""Unit tests for watari_snkrdunk.parser and dates (no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from watari_core.conditions import Condition
from watari_core.models import SourceEnum, SourceTypeEnum
from watari_snkrdunk.dates import parse_snkrdunk_date
from watari_snkrdunk.parser import parse_sales_history

JST = timezone(timedelta(hours=9))


class TestParseSnkrdunkDate:
    def test_absolute_jst_to_utc(self):
        dt = parse_snkrdunk_date("2026/03/21")
        assert dt.tzinfo == UTC
        assert (dt.year, dt.month, dt.day) == (2026, 3, 20)
        assert dt.hour == 15

    def test_relative_minutes(self):
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=JST)
        dt = parse_snkrdunk_date("40分前", now=now)
        assert dt == datetime(2026, 4, 21, 2, 20, tzinfo=UTC)

    def test_relative_hours(self):
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=JST)
        dt = parse_snkrdunk_date("4時間前", now=now)
        assert dt == datetime(2026, 4, 20, 23, 0, tzinfo=UTC)

    def test_relative_days(self):
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=JST)
        dt = parse_snkrdunk_date("1日前", now=now)
        assert dt == datetime(2026, 4, 20, 3, 0, tzinfo=UTC)

    def test_relative_weeks(self):
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=JST)
        dt = parse_snkrdunk_date("2週間前", now=now)
        assert (dt.tzinfo, dt.day) == (UTC, 7)

    def test_relative_months(self):
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=JST)
        dt = parse_snkrdunk_date("3ヶ月前", now=now)
        delta = now.astimezone(UTC) - dt
        assert delta == timedelta(days=90)

    def test_relative_years(self):
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=JST)
        dt = parse_snkrdunk_date("1年前", now=now)
        delta = now.astimezone(UTC) - dt
        assert delta == timedelta(days=365)

    def test_unknown_returns_reference_now(self):
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=JST)
        dt = parse_snkrdunk_date("???", now=now)
        assert dt == now.astimezone(UTC)


SAMPLE_ENTRIES = [
    {"condition": "S", "price": 500, "date": "2026/03/21"},
    {"condition": "A", "price": 400, "date": "1日前"},
    {"condition": "B", "price": 300, "date": "2026/03/22"},
    {"condition": "C", "price": 200, "date": "2026/03/23"},
    {"condition": "D", "price": 999, "date": "2026/03/24"},  # dropped (unknown)
    {"condition": "A", "price": 0, "date": "2026/03/25"},  # dropped (bad price)
    {"condition": "A", "price": 350, "date": 12345},  # dropped (bad date)
]


class TestParseSalesHistory:
    def test_maps_valid_entries(self):
        rows, graded = parse_sales_history(
            SAMPLE_ENTRIES,
            card_id="jp-sv2a-183",
            apparel_id=12345,
            scrape_run_id=7,
        )
        assert len(rows) == 4
        conds = [r["condition"] for r in rows]
        assert conds == [
            Condition.A, Condition.A, Condition.B, Condition.C,
        ]
        assert graded == []

    def test_sets_source_and_type(self):
        rows, _ = parse_sales_history(
            SAMPLE_ENTRIES[:1],
            card_id="jp-sv2a-183",
            apparel_id=1,
            scrape_run_id=None,
        )
        assert rows[0]["source"] == SourceEnum.snkrdunk
        assert rows[0]["source_type"] == SourceTypeEnum.sold
        assert rows[0]["stock_qty"] is None

    def test_external_url_built_from_apparel_id(self):
        rows, _ = parse_sales_history(
            SAMPLE_ENTRIES[:1],
            card_id="jp-sv2a-183",
            apparel_id=555,
            scrape_run_id=None,
        )
        assert rows[0]["external_url"] == "https://snkrdunk.com/apparels/555"

    def test_drops_unknown_condition(self):
        rows, graded = parse_sales_history(
            [{"condition": "X", "price": 100, "date": "2026/03/21"}],
            card_id="jp-sv2a-183",
            apparel_id=1,
            scrape_run_id=None,
        )
        assert rows == []
        assert graded == []

    def test_drops_nonint_price(self):
        rows, graded = parse_sales_history(
            [{"condition": "A", "price": "100", "date": "2026/03/21"}],
            card_id="jp-sv2a-183",
            apparel_id=1,
            scrape_run_id=None,
        )
        assert rows == []
        assert graded == []

    def test_scrape_run_id_passed_through(self):
        rows, _ = parse_sales_history(
            SAMPLE_ENTRIES[:1],
            card_id="jp-sv2a-183",
            apparel_id=1,
            scrape_run_id=42,
        )
        assert rows[0]["scrape_run_id"] == 42

    # --- Graded path ---------------------------------------------------------

    def test_psa10_entry_goes_to_graded(self):
        entries = [{"condition": "PSA10", "price": 9900, "date": "2026/03/21"}]
        rows, graded = parse_sales_history(
            entries, card_id="jp-sv9a-070-normal", apparel_id=544501, scrape_run_id=1
        )
        assert rows == []
        assert len(graded) == 1
        g = graded[0]
        assert g["grade_company"] == "PSA"
        assert g["grade_score"] == 10.0
        assert g["price_jpy"] == 9900
        assert g["source"] == SourceEnum.snkrdunk.value
        assert g["source_type"] == SourceTypeEnum.sold.value
        assert g["stock_qty"] is None
        assert g["external_url"] == "https://snkrdunk.com/apparels/544501"

    def test_psa9_entry_goes_to_graded(self):
        entries = [{"condition": "PSA9", "price": 5000, "date": "2026/03/21"}]
        _, graded = parse_sales_history(
            entries, card_id="jp-sv9a-070-normal", apparel_id=1, scrape_run_id=None
        )
        assert len(graded) == 1
        assert graded[0]["grade_score"] == 9.0

    def test_bgs95_entry_goes_to_graded(self):
        entries = [{"condition": "BGS9.5", "price": 8000, "date": "2026/03/21"}]
        _, graded = parse_sales_history(
            entries, card_id="jp-sv9a-070-normal", apparel_id=1, scrape_run_id=None
        )
        assert len(graded) == 1
        assert graded[0]["grade_company"] == "BGS"
        assert graded[0]["grade_score"] == 9.5

    def test_psa8_ijou_dropped(self):
        """'PSA8以下' is ambiguous — dropped, not stored in either table."""
        entries = [{"condition": "PSA8以下", "price": 3000, "date": "2026/03/21"}]
        rows, graded = parse_sales_history(
            entries, card_id="jp-sv9a-070-normal", apparel_id=1, scrape_run_id=None
        )
        assert rows == []
        assert graded == []

    def test_bgs10_bl_dropped(self):
        """'BGS10 BL' (Black Label) has a non-numeric suffix — dropped."""
        entries = [{"condition": "BGS10 BL", "price": 50000, "date": "2026/03/21"}]
        rows, graded = parse_sales_history(
            entries, card_id="jp-sv9a-070-normal", apparel_id=1, scrape_run_id=None
        )
        assert rows == []
        assert graded == []

    def test_mixed_ungraded_and_graded(self):
        """Both condition types in same entry list are split correctly."""
        entries = [
            {"condition": "A", "price": 1200, "date": "2026/03/21"},
            {"condition": "PSA10", "price": 9900, "date": "2026/03/21"},
            {"condition": "B", "price": 800, "date": "2026/03/21"},
            {"condition": "PSA9", "price": 5000, "date": "2026/03/21"},
            {"condition": "PSA8以下", "price": 3000, "date": "2026/03/21"},  # dropped
        ]
        rows, graded = parse_sales_history(
            entries, card_id="jp-sv9a-070-normal", apparel_id=1, scrape_run_id=None
        )
        assert len(rows) == 2
        assert len(graded) == 2
        assert {g["grade_score"] for g in graded} == {10.0, 9.0}
