"""Unit tests for pokeprice_snkrdunk.parser and dates (no network)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pokeprice_core.conditions import Condition
from pokeprice_core.models import SourceEnum, SourceTypeEnum
from pokeprice_snkrdunk.dates import parse_snkrdunk_date
from pokeprice_snkrdunk.parser import parse_sales_history

JST = timezone(timedelta(hours=9))


class TestParseSnkrdunkDate:
    def test_absolute_jst_to_utc(self):
        dt = parse_snkrdunk_date("2026/03/21")
        assert dt.tzinfo == timezone.utc
        assert (dt.year, dt.month, dt.day) == (2026, 3, 20)
        assert dt.hour == 15

    def test_relative_minutes(self):
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=JST)
        dt = parse_snkrdunk_date("40分前", now=now)
        assert dt == datetime(2026, 4, 21, 2, 20, tzinfo=timezone.utc)

    def test_relative_hours(self):
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=JST)
        dt = parse_snkrdunk_date("4時間前", now=now)
        assert dt == datetime(2026, 4, 20, 23, 0, tzinfo=timezone.utc)

    def test_relative_days(self):
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=JST)
        dt = parse_snkrdunk_date("1日前", now=now)
        assert dt == datetime(2026, 4, 20, 3, 0, tzinfo=timezone.utc)

    def test_relative_weeks(self):
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=JST)
        dt = parse_snkrdunk_date("2週間前", now=now)
        assert (dt.tzinfo, dt.day) == (timezone.utc, 7)

    def test_relative_months(self):
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=JST)
        dt = parse_snkrdunk_date("3ヶ月前", now=now)
        delta = now.astimezone(timezone.utc) - dt
        assert delta == timedelta(days=90)

    def test_relative_years(self):
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=JST)
        dt = parse_snkrdunk_date("1年前", now=now)
        delta = now.astimezone(timezone.utc) - dt
        assert delta == timedelta(days=365)

    def test_unknown_returns_reference_now(self):
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=JST)
        dt = parse_snkrdunk_date("???", now=now)
        assert dt == now.astimezone(timezone.utc)


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
        rows = parse_sales_history(
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

    def test_sets_source_and_type(self):
        rows = parse_sales_history(
            SAMPLE_ENTRIES[:1],
            card_id="jp-sv2a-183",
            apparel_id=1,
            scrape_run_id=None,
        )
        assert rows[0]["source"] == SourceEnum.snkrdunk
        assert rows[0]["source_type"] == SourceTypeEnum.sold
        assert rows[0]["stock_qty"] is None

    def test_external_url_built_from_apparel_id(self):
        rows = parse_sales_history(
            SAMPLE_ENTRIES[:1],
            card_id="jp-sv2a-183",
            apparel_id=555,
            scrape_run_id=None,
        )
        assert rows[0]["external_url"] == "https://snkrdunk.com/apparels/555"

    def test_drops_unknown_condition(self):
        rows = parse_sales_history(
            [{"condition": "X", "price": 100, "date": "2026/03/21"}],
            card_id="jp-sv2a-183",
            apparel_id=1,
            scrape_run_id=None,
        )
        assert rows == []

    def test_drops_nonint_price(self):
        rows = parse_sales_history(
            [{"condition": "A", "price": "100", "date": "2026/03/21"}],
            card_id="jp-sv2a-183",
            apparel_id=1,
            scrape_run_id=None,
        )
        assert rows == []

    def test_scrape_run_id_passed_through(self):
        rows = parse_sales_history(
            SAMPLE_ENTRIES[:1],
            card_id="jp-sv2a-183",
            apparel_id=1,
            scrape_run_id=42,
        )
        assert rows[0]["scrape_run_id"] == 42
