"""Unit tests for the FastAPI read-side app (packages/api)."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterable
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from watari_api.auth import AuthContext
from watari_api.deps import get_session
from watari_api.main import create_app
from watari_api.ratelimit import rate_limit_dep
from sqlalchemy import Select

# --- Fakes ---------------------------------------------------------------


class FakeResult:
    """A stand-in for ``sqlalchemy.engine.Result`` that returns canned data."""

    def __init__(
        self,
        *,
        scalars: Iterable[Any] | None = None,
        rows: list[dict[str, Any]] | None = None,
        scalar: Any = ...,
    ) -> None:
        self._scalars = list(scalars) if scalars is not None else None
        self._rows = rows
        self._scalar = scalar

    def scalars(self) -> FakeResult:
        return self

    def all(self) -> list[Any]:
        if self._scalars is not None:
            return self._scalars
        if self._rows is not None:
            return [_RowLike(r) for r in self._rows]
        return []

    def scalar_one_or_none(self) -> Any:
        if self._scalar is ...:
            return self._scalars[0] if self._scalars else None
        return self._scalar

    def scalar_one(self) -> Any:
        if self._scalar is not ...:
            return self._scalar
        if self._scalars:
            return self._scalars[0]
        raise AssertionError("scalar_one() called on empty FakeResult")

    def mappings(self) -> FakeResult:
        return self

    def one_or_none(self) -> Any:
        if self._rows:
            return _RowLike(self._rows[0])
        return None


class _RowLike:
    """Mimics a SQLAlchemy Row so ``row._mapping`` / ``dict(row)`` both work."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._mapping = data
        for k, v in data.items():
            setattr(self, k, v)

    def keys(self) -> Iterable[str]:
        return self._mapping.keys()

    def __iter__(self) -> Any:
        return iter(self._mapping.items())

    def __getitem__(self, key: str) -> Any:
        return self._mapping[key]


class FakeSession:
    """Async session that pops canned ``FakeResult``\\s off a queue."""

    def __init__(self, results: list[FakeResult]) -> None:
        self._results = list(results)
        self.calls: list[Any] = []

    async def execute(self, stmt: Any, params: Any | None = None) -> FakeResult:
        self.calls.append((stmt, params))
        if not self._results:
            raise AssertionError("FakeSession exhausted; unexpected execute() call")
        return self._results.pop(0)

    async def commit(self) -> None:  # no-op for fake; auth.py may call this
        return None


def _override_session(session: FakeSession) -> Any:
    async def _gen() -> AsyncGenerator[FakeSession, None]:
        yield session

    return _gen


async def _anonymous_ratelimit() -> AuthContext:
    """Replacement for ``rate_limit_dep`` that always admits as anonymous."""
    return AuthContext(
        authed=False,
        tier="free",
        api_key_id=None,
        key_prefix=None,
        identifier="ip:testclient",
    )


@pytest.fixture()
def client_factory():  # type: ignore[no-untyped-def]
    """Return a factory that builds a TestClient with a preloaded FakeSession."""

    def _make(results: list[FakeResult]) -> tuple[TestClient, FakeSession]:
        app = create_app()
        session = FakeSession(results)
        app.dependency_overrides[get_session] = _override_session(session)
        app.dependency_overrides[rate_limit_dep] = _anonymous_ratelimit
        return TestClient(app), session

    return _make


def test_healthz_returns_ok() -> None:
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def _fake_set_row(set_code: str = "SV2A", era: str = "sv") -> Any:
    now = datetime(2025, 1, 1, tzinfo=UTC)
    # pydantic's from_attributes mode will read these attrs off the object.
    return _RowLike(
        {
            "set_code": set_code,
            "era_block": era,
            "language": "jp",
            "name_ja": "ポケモンカード151",
            "name_en": "Pokemon Card 151",
            "release_date": None,
            "total": 210,
            "parent_set_code": None,
            "tcgdex_id": "sv2a",
            "source_refs": {},
            "created_at": now,
            "updated_at": now,
        }
    )


# --- Sets ----------------------------------------------------------------


def test_list_sets_returns_all(client_factory) -> None:  # type: ignore[no-untyped-def]
    rows = [_fake_set_row("SV2A"), _fake_set_row("M2A", era="me")]
    # list_sets now issues a count query first, then the data query.
    client, _ = client_factory(
        [
            FakeResult(scalar=2),
            FakeResult(scalars=rows),
            FakeResult(rows=[{"set_code": "SV2A", "sum": 12345}]),
        ]
    )
    resp = client.get("/jp/sets")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert {d["set_code"] for d in data} == {"SV2A", "M2A"}


def test_list_sets_returns_total_count_header(client_factory) -> None:  # type: ignore[no-untyped-def]
    rows = [_fake_set_row("SV2A")]
    client, _ = client_factory(
        [FakeResult(scalar=1), FakeResult(scalars=rows), FakeResult(rows=[])]
    )
    resp = client.get("/jp/sets")
    assert resp.headers["X-Total-Count"] == "1"


def test_list_sets_returns_cache_header(client_factory) -> None:  # type: ignore[no-untyped-def]
    client, _ = client_factory(
        [FakeResult(scalar=0), FakeResult(scalars=[]), FakeResult(rows=[])]
    )
    resp = client.get("/jp/sets")
    assert "max-age=3600" in resp.headers["Cache-Control"]


def test_list_sets_filters_by_era(client_factory) -> None:  # type: ignore[no-untyped-def]
    rows = [_fake_set_row("M2A", era="me")]
    client, session = client_factory(
        [FakeResult(scalar=1), FakeResult(scalars=rows), FakeResult(rows=[])]
    )
    resp = client.get("/jp/sets?era=me")
    assert resp.status_code == 200
    assert [d["set_code"] for d in resp.json()] == ["M2A"]
    stmt, _ = session.calls[0]
    assert isinstance(stmt, Select)


def test_get_set_404_when_missing(client_factory) -> None:  # type: ignore[no-untyped-def]
    client, _ = client_factory([FakeResult(scalar=None)])
    resp = client.get("/jp/sets/NOPE")
    assert resp.status_code == 404


def test_get_set_returns_row(client_factory) -> None:  # type: ignore[no-untyped-def]
    row = _fake_set_row("SV2A")
    client, _ = client_factory([FakeResult(scalar=row), FakeResult(rows=[])])
    resp = client.get("/jp/sets/SV2A")
    assert resp.status_code == 200
    assert resp.json()["set_code"] == "SV2A"


def test_get_set_returns_cache_header(client_factory) -> None:  # type: ignore[no-untyped-def]
    row = _fake_set_row("SV2A")
    client, _ = client_factory([FakeResult(scalar=row), FakeResult(rows=[])])
    resp = client.get("/jp/sets/SV2A")
    assert "max-age=3600" in resp.headers["Cache-Control"]


def test_list_sets_includes_total_value_jpy(client_factory) -> None:  # type: ignore[no-untyped-def]
    row = _fake_set_row("SV2A")
    client, _ = client_factory(
        [
            FakeResult(scalar=1),
            FakeResult(scalars=[row]),
            FakeResult(rows=[{"set_code": "SV2A", "sum": 7777}]),
        ]
    )
    resp = client.get("/jp/sets")
    assert resp.status_code == 200
    assert resp.json()[0]["total_value_jpy"] == 7777


def test_list_sets_sort_by_value_desc(client_factory) -> None:  # type: ignore[no-untyped-def]
    rows = [_fake_set_row("A1"), _fake_set_row("A2")]
    client, _ = client_factory(
        [
            FakeResult(scalar=2),
            FakeResult(scalars=rows),
            FakeResult(rows=[{"set_code": "A1", "sum": 1000}, {"set_code": "A2", "sum": 2000}]),
        ]
    )
    resp = client.get("/jp/sets?sort=value&order=desc")
    assert [d["set_code"] for d in resp.json()] == ["A2", "A1"]


def test_list_sets_sort_by_release_date_asc(client_factory) -> None:  # type: ignore[no-untyped-def]
    old = _fake_set_row("OLD")
    new = _fake_set_row("NEW")
    old.release_date = datetime(2023, 1, 1, tzinfo=UTC).date()
    new.release_date = datetime(2024, 1, 1, tzinfo=UTC).date()
    client, _ = client_factory(
        [FakeResult(scalar=2), FakeResult(scalars=[new, old]), FakeResult(rows=[])]
    )
    resp = client.get("/jp/sets?sort=release_date&order=asc")
    assert [d["set_code"] for d in resp.json()] == ["OLD", "NEW"]


def test_list_sets_sort_by_release_date_desc_nulls_last(client_factory) -> None:  # type: ignore[no-untyped-def]
    dated = _fake_set_row("DATED")
    undated = _fake_set_row("UNDATED")
    dated.release_date = datetime(2024, 1, 1, tzinfo=UTC).date()
    undated.release_date = None
    client, _ = client_factory(
        [FakeResult(scalar=2), FakeResult(scalars=[dated, undated]), FakeResult(rows=[])]
    )
    resp = client.get("/jp/sets?sort=release_date&order=desc")
    assert [d["set_code"] for d in resp.json()] == ["DATED", "UNDATED"]


def test_list_sets_sort_by_value_desc_nulls_last(client_factory) -> None:  # type: ignore[no-untyped-def]
    rows = [_fake_set_row("A1"), _fake_set_row("A2")]
    client, _ = client_factory(
        [
            FakeResult(scalar=2),
            FakeResult(scalars=rows),
            FakeResult(rows=[{"set_code": "A1", "sum": 1000}]),
        ]
    )
    resp = client.get("/jp/sets?sort=value&order=desc")
    assert [d["set_code"] for d in resp.json()] == ["A1", "A2"]


# --- Cards ---------------------------------------------------------------


def _fake_artwork_row(local_id: str = "089") -> dict[str, Any]:
    return {
        "artwork_id": f"jp-sv2a-{local_id}",
        "set_code": "SV2A",
        "local_id": local_id,
        "name_ja": "ベトベトン",
        "name_en": "Muk",
        "rarity_code": "U",
        "image_url": "https://example.com/muk.png",
        "illustrator": None,
        "category": "card",
        "language": "jp",
    }


def _fake_variant_row(artwork_id: str, variant: str, *, tracked: bool = True) -> dict[str, Any]:
    return {
        "artwork_id": artwork_id,
        "variant": variant,
        "card_id": f"{artwork_id}-{variant}",
        "is_tracked": tracked,
    }


def test_list_cards_for_set_returns_artwork_details(client_factory) -> None:  # type: ignore[no-untyped-def]
    set_exists = FakeResult(scalar="SV2A")
    count = FakeResult(scalar=1)
    artworks = FakeResult(rows=[_fake_artwork_row("089")])
    variants = FakeResult(
        rows=[
            _fake_variant_row("jp-sv2a-089", "master_ball_mirror"),
            _fake_variant_row("jp-sv2a-089", "normal"),
        ]
    )
    client, _ = client_factory([set_exists, count, artworks, variants])
    resp = client.get("/jp/sets/SV2A/cards")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name_ja"] == "ベトベトン"
    assert [v["variant"] for v in data[0]["variants"]] == ["normal", "master_ball_mirror"]


def test_list_cards_returns_total_count_header(client_factory) -> None:  # type: ignore[no-untyped-def]
    set_exists = FakeResult(scalar="SV2A")
    count = FakeResult(scalar=42)
    artworks = FakeResult(rows=[_fake_artwork_row("089")])
    variants = FakeResult(rows=[_fake_variant_row("jp-sv2a-089", "normal")])
    client, _ = client_factory([set_exists, count, artworks, variants])
    resp = client.get("/jp/sets/SV2A/cards")
    assert resp.headers["X-Total-Count"] == "42"


def test_list_cards_returns_cache_header(client_factory) -> None:  # type: ignore[no-untyped-def]
    set_exists = FakeResult(scalar="SV2A")
    count = FakeResult(scalar=0)
    artworks = FakeResult(rows=[])
    client, _ = client_factory([set_exists, count, artworks])
    resp = client.get("/jp/sets/SV2A/cards")
    assert "max-age=3600" in resp.headers["Cache-Control"]


def test_list_cards_pagination_params_accepted(client_factory) -> None:  # type: ignore[no-untyped-def]
    set_exists = FakeResult(scalar="SV2A")
    count = FakeResult(scalar=200)
    artworks = FakeResult(rows=[_fake_artwork_row("089")])
    variants = FakeResult(rows=[_fake_variant_row("jp-sv2a-089", "normal")])
    client, _ = client_factory([set_exists, count, artworks, variants])
    resp = client.get("/jp/sets/SV2A/cards?limit=50&offset=100")
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "200"


def test_list_cards_404_for_unknown_set(client_factory) -> None:  # type: ignore[no-untyped-def]
    client, _ = client_factory([FakeResult(scalar=None)])
    resp = client.get("/jp/sets/NOPE/cards")
    assert resp.status_code == 404


def test_get_card_by_set_and_local_id(client_factory) -> None:  # type: ignore[no-untyped-def]
    artwork = FakeResult(rows=[_fake_artwork_row("089")])
    variants = FakeResult(rows=[_fake_variant_row("jp-sv2a-089", "normal")])
    client, _ = client_factory([artwork, variants])
    resp = client.get("/jp/cards/SV2A/089")
    assert resp.status_code == 200
    body = resp.json()
    assert body["artwork_id"] == "jp-sv2a-089"
    assert body["variants"][0]["card_id"] == "jp-sv2a-089-normal"


def test_get_card_returns_cache_header(client_factory) -> None:  # type: ignore[no-untyped-def]
    artwork = FakeResult(rows=[_fake_artwork_row("089")])
    variants = FakeResult(rows=[_fake_variant_row("jp-sv2a-089", "normal")])
    client, _ = client_factory([artwork, variants])
    resp = client.get("/jp/cards/SV2A/089")
    assert "max-age=3600" in resp.headers["Cache-Control"]


def test_get_card_404(client_factory) -> None:  # type: ignore[no-untyped-def]
    client, _ = client_factory([FakeResult(rows=[])])
    resp = client.get("/jp/cards/SV2A/999")
    assert resp.status_code == 404


# --- Batch card lookup ---------------------------------------------------


def test_batch_full_code_found(client_factory) -> None:  # type: ignore[no-untyped-def]
    # "sv2a 089/210" → one artwork, one variant
    artwork_rows = FakeResult(rows=[_fake_artwork_row("089")])
    variant_rows = FakeResult(rows=[_fake_variant_row("jp-sv2a-089", "normal")])
    market_rows = FakeResult(rows=[])
    client, _ = client_factory([artwork_rows, variant_rows, market_rows])
    resp = client.get("/jp/cards/batch?codes=sv2a+089%2F210")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    item = data[0]
    assert item["error"] is None
    assert item["card"]["artwork_id"] == "jp-sv2a-089"
    assert item["candidates"] == []


def test_batch_full_code_not_found(client_factory) -> None:  # type: ignore[no-untyped-def]
    # paired query returns no rows
    client, _ = client_factory([FakeResult(rows=[])])
    resp = client.get("/jp/cards/batch?codes=sv2a+999")
    assert resp.status_code == 200
    item = resp.json()[0]
    assert item["error"] == "not_found"
    assert item["card"] is None


def test_batch_id_only_returns_missing_set_code(client_factory) -> None:  # type: ignore[no-untyped-def]
    # Tokens without a set code are rejected immediately — no DB queries issued
    client, _ = client_factory([])  # empty queue confirms no DB calls
    resp = client.get("/jp/cards/batch?codes=089")
    assert resp.status_code == 200
    item = resp.json()[0]
    assert item["error"] == "missing_set_code"
    assert item["card"] is None


def test_batch_fraction_only_returns_missing_set_code(client_factory) -> None:  # type: ignore[no-untyped-def]
    # "066/062" without a set code prefix is also rejected
    client, _ = client_factory([])
    resp = client.get("/jp/cards/batch?codes=066%2F062")
    assert resp.status_code == 200
    assert resp.json()[0]["error"] == "missing_set_code"


def test_batch_parse_error(client_factory) -> None:  # type: ignore[no-untyped-def]
    # token "sv3a /" has no usable local_id after stripping the denominator
    client, _ = client_factory([])  # no DB calls expected
    resp = client.get("/jp/cards/batch?codes=sv3a+%2F")
    assert resp.status_code == 200
    assert resp.json()[0]["error"] == "parse_error"


def test_batch_mixed_found_and_not_found(client_factory) -> None:  # type: ignore[no-untyped-def]
    # "sv2a 089" found, "sv2a 999" not found — both are paired items, one query
    artwork_rows = FakeResult(rows=[_fake_artwork_row("089")])
    variant_rows = FakeResult(rows=[_fake_variant_row("jp-sv2a-089", "normal")])
    market_rows = FakeResult(rows=[])
    client, _ = client_factory([artwork_rows, variant_rows, market_rows])
    resp = client.get("/jp/cards/batch?codes=sv2a+089,sv2a+999")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    found = next(d for d in data if d["input"] == "sv2a 089")
    missing = next(d for d in data if d["input"] == "sv2a 999")
    assert found["error"] is None
    assert found["card"]["artwork_id"] == "jp-sv2a-089"
    assert missing["error"] == "not_found"


def test_batch_fraction_notation_strips_denominator(client_factory) -> None:  # type: ignore[no-untyped-def]
    # "sv2a 089/210" should resolve the same as "sv2a 089"
    artwork_rows = FakeResult(rows=[_fake_artwork_row("089")])
    variant_rows = FakeResult(rows=[_fake_variant_row("jp-sv2a-089", "normal")])
    market_rows = FakeResult(rows=[])
    client, _ = client_factory([artwork_rows, variant_rows, market_rows])
    resp = client.get("/jp/cards/batch?codes=sv2a+089%2F210")
    item = resp.json()[0]
    assert item["error"] is None
    assert item["card"]["local_id"] == "089"


def test_batch_empty_codes_returns_empty_list(client_factory) -> None:  # type: ignore[no-untyped-def]
    client, _ = client_factory([])
    resp = client.get("/jp/cards/batch?codes=")
    assert resp.status_code == 200
    assert resp.json() == []


def test_batch_cache_header_set(client_factory) -> None:  # type: ignore[no-untyped-def]
    artwork_rows = FakeResult(rows=[_fake_artwork_row("089")])
    variant_rows = FakeResult(rows=[_fake_variant_row("jp-sv2a-089", "normal")])
    market_rows = FakeResult(rows=[])
    client, _ = client_factory([artwork_rows, variant_rows, market_rows])
    resp = client.get("/jp/cards/batch?codes=sv2a+089")
    assert "max-age=3600" in resp.headers["Cache-Control"]


def test_batch_includes_market_price(client_factory) -> None:  # type: ignore[no-untyped-def]
    artwork_rows = FakeResult(rows=[_fake_artwork_row("089")])
    variant_rows = FakeResult(rows=[_fake_variant_row("jp-sv2a-089", "normal")])
    market_rows = FakeResult(
        rows=[{"card_id": "jp-sv2a-089-normal", "market_price_jpy": 3500, "source_used": "snkrdunk"}]
    )
    client, _ = client_factory([artwork_rows, variant_rows, market_rows])
    resp = client.get("/jp/cards/batch?codes=sv2a+089")
    assert resp.status_code == 200
    item = resp.json()[0]
    assert item["market_price_jpy"] == 3500
    assert item["market_price_source_used"] == "snkrdunk"
    assert item["market_price_variant"] == "normal"


def test_batch_market_price_none_when_no_price_data(client_factory) -> None:  # type: ignore[no-untyped-def]
    artwork_rows = FakeResult(rows=[_fake_artwork_row("089")])
    variant_rows = FakeResult(rows=[_fake_variant_row("jp-sv2a-089", "normal")])
    market_rows = FakeResult(rows=[])  # mv_market_price has no row for this card
    client, _ = client_factory([artwork_rows, variant_rows, market_rows])
    resp = client.get("/jp/cards/batch?codes=sv2a+089")
    item = resp.json()[0]
    assert item["error"] is None
    assert item["market_price_jpy"] is None
    assert item["market_price_source_used"] is None
    assert item["market_price_variant"] == "normal"  # variant still reported


def test_batch_mixed_set_code_and_missing_set_code(client_factory) -> None:  # type: ignore[no-untyped-def]
    # One token has a set code (queried), the other does not (rejected immediately)
    artwork_rows = FakeResult(rows=[_fake_artwork_row("089")])
    variant_rows = FakeResult(rows=[_fake_variant_row("jp-sv2a-089", "normal")])
    market_rows = FakeResult(rows=[])
    client, _ = client_factory([artwork_rows, variant_rows, market_rows])
    resp = client.get("/jp/cards/batch?codes=sv2a+089,089")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    found = next(d for d in data if d["input"] == "sv2a 089")
    missing = next(d for d in data if d["input"] == "089")
    assert found["error"] is None
    assert found["card"]["artwork_id"] == "jp-sv2a-089"
    assert missing["error"] == "missing_set_code"
    assert missing["market_price_jpy"] is None


def test_search_cards_matches_name_ja(client_factory) -> None:  # type: ignore[no-untyped-def]
    count = FakeResult(scalar=1)
    artworks = FakeResult(
        rows=[
            {
                **_fake_artwork_row("089"),
                "set_name_ja": "ポケモンカード151",
                "set_name_en": "Pokemon Card 151",
                "set_release_date": None,
            }
        ]
    )
    variants = FakeResult(rows=[_fake_variant_row("jp-sv2a-089", "normal")])
    floors = FakeResult(rows=[{"artwork_id": "jp-sv2a-089", "price_jpy": 1200}])
    market = FakeResult(
        rows=[
            {
                "card_id": "jp-sv2a-089-normal",
                "market_price_jpy": 1500,
                "source_used": "snkrdunk",
            }
        ]
    )
    client, _ = client_factory([count, artworks, variants, floors, market])
    resp = client.get("/jp/cards/search?q=ベト")
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["artwork_id"] == "jp-sv2a-089"
    assert body[0]["cardrush_a_floor_jpy"] == 1200
    assert body[0]["market_price_jpy"] == 1500
    assert body[0]["market_price_source_used"] == "snkrdunk"


def test_search_cards_matches_local_id(client_factory) -> None:  # type: ignore[no-untyped-def]
    count = FakeResult(scalar=1)
    artworks = FakeResult(
        rows=[
            {
                **_fake_artwork_row("089"),
                "set_name_ja": "ポケモンカード151",
                "set_name_en": "Pokemon Card 151",
                "set_release_date": None,
            }
        ]
    )
    variants = FakeResult(rows=[_fake_variant_row("jp-sv2a-089", "normal")])
    floors = FakeResult(rows=[])
    market = FakeResult(rows=[])
    client, _ = client_factory([count, artworks, variants, floors, market])
    resp = client.get("/jp/cards/search?q=089")
    assert resp.status_code == 200
    assert resp.json()[0]["local_id"] == "089"


def test_search_cards_matches_set_code(client_factory) -> None:  # type: ignore[no-untyped-def]
    count = FakeResult(scalar=1)
    artworks = FakeResult(
        rows=[
            {
                **_fake_artwork_row("001"),
                "set_name_ja": "ポケモンカード151",
                "set_name_en": "Pokemon Card 151",
                "set_release_date": None,
            }
        ]
    )
    variants = FakeResult(rows=[_fake_variant_row("jp-sv2a-001", "normal")])
    floors = FakeResult(rows=[])
    market = FakeResult(rows=[])
    client, _ = client_factory([count, artworks, variants, floors, market])
    resp = client.get("/jp/cards/search?q=sv2a")
    assert resp.status_code == 200
    assert resp.json()[0]["set_code"] == "SV2A"


def test_search_cards_filters_by_set_and_rarity(client_factory) -> None:  # type: ignore[no-untyped-def]
    count = FakeResult(scalar=0)
    artworks = FakeResult(rows=[])
    client, _ = client_factory([count, artworks])
    resp = client.get("/jp/cards/search?q=muk&set_code=SV2A&rarity=U")
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "0"


def test_search_cards_returns_total_count_header(client_factory) -> None:  # type: ignore[no-untyped-def]
    count = FakeResult(scalar=42)
    artworks = FakeResult(rows=[])
    client, _ = client_factory([count, artworks])
    resp = client.get("/jp/cards/search?q=sv")
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "42"


def test_search_cards_rejects_blank_query(client_factory) -> None:  # type: ignore[no-untyped-def]
    client, session = client_factory([])
    resp = client.get("/jp/cards/search?q=%20%20%20")
    assert resp.status_code == 422
    assert session.calls == []


def test_list_card_rarities_returns_distinct_codes(client_factory) -> None:  # type: ignore[no-untyped-def]
    rarities = FakeResult(scalars=["AR", "SAR", "UR"])
    client, _ = client_factory([rarities])
    resp = client.get("/jp/cards/rarities")
    assert resp.status_code == 200
    assert resp.json() == ["AR", "SAR", "UR"]
    assert "max-age=3600" in resp.headers["Cache-Control"]


def test_list_card_rarities_filters_by_set_code(client_factory) -> None:  # type: ignore[no-untyped-def]
    rarities = FakeResult(scalars=["RR", "SR"])
    client, _ = client_factory([rarities])
    resp = client.get("/jp/cards/rarities?set_code=SV1S")
    assert resp.status_code == 200
    assert resp.json() == ["RR", "SR"]


# --- Prices / spread -----------------------------------------------------


def _fake_card_scalars(variant: str = "normal") -> FakeResult:
    """Single-query _resolve_card result: list of Card-like rows."""
    return FakeResult(
        scalars=[
            _RowLike(
                {
                    "card_id": f"jp-sv2a-089-{variant}",
                    "set_code": "SV2A",
                    "local_id": "089",
                    "variant": variant,
                }
            )
        ]
    )


def test_latest_prices_from_mv(client_factory) -> None:  # type: ignore[no-untyped-def]
    now = datetime(2025, 4, 1, tzinfo=UTC)
    resolve = _fake_card_scalars("normal")
    mv_rows = FakeResult(
        rows=[
            {
                "card_id": "jp-sv2a-089-normal",
                "source": "cardrush",
                "condition": "NM",
                "price_jpy": 500,
                "stock_qty": 3,
                "observed_at": now,
            },
            {
                "card_id": "jp-sv2a-089-normal",
                "source": "snkrdunk",
                "condition": "NM",
                "price_jpy": 450,
                "stock_qty": None,
                "observed_at": now,
            },
        ]
    )
    client, _ = client_factory([resolve, mv_rows])
    resp = client.get("/jp/cards/SV2A/089/prices")
    assert resp.status_code == 200
    prices = resp.json()
    assert len(prices) == 2
    assert {p["source"] for p in prices} == {"cardrush", "snkrdunk"}


def test_latest_prices_returns_cache_and_etag_headers(client_factory) -> None:  # type: ignore[no-untyped-def]
    now = datetime(2025, 4, 1, tzinfo=UTC)
    resolve = _fake_card_scalars("normal")
    mv_rows = FakeResult(
        rows=[
            {
                "card_id": "jp-sv2a-089-normal",
                "source": "cardrush",
                "condition": "NM",
                "price_jpy": 500,
                "stock_qty": None,
                "observed_at": now,
            }
        ]
    )
    client, _ = client_factory([resolve, mv_rows])
    resp = client.get("/jp/cards/SV2A/089/prices")
    assert resp.status_code == 200
    assert "max-age=300" in resp.headers["Cache-Control"]
    assert resp.headers.get("ETag", "").startswith('"')


def test_latest_prices_conditional_get_returns_304(client_factory) -> None:  # type: ignore[no-untyped-def]
    now = datetime(2025, 4, 1, tzinfo=UTC)
    price_row = {
        "card_id": "jp-sv2a-089-normal",
        "source": "cardrush",
        "condition": "NM",
        "price_jpy": 500,
        "stock_qty": None,
        "observed_at": now,
    }

    # First request: get the ETag.
    resolve1 = _fake_card_scalars()
    mv1 = FakeResult(rows=[price_row])
    client, _ = client_factory([resolve1, mv1])
    resp1 = client.get("/jp/cards/SV2A/089/prices")
    etag = resp1.headers["ETag"]

    # Second request with If-None-Match: expect 304.
    resolve2 = _fake_card_scalars()
    mv2 = FakeResult(rows=[price_row])
    client2, _ = client_factory([resolve2, mv2])
    resp2 = client2.get("/jp/cards/SV2A/089/prices", headers={"If-None-Match": etag})
    assert resp2.status_code == 304


def test_history_returns_no_store_cache_header(client_factory) -> None:  # type: ignore[no-untyped-def]
    resolve = _fake_card_scalars()
    history_rows = FakeResult(scalars=[])
    client, _ = client_factory([resolve, history_rows])
    resp = client.get("/jp/cards/SV2A/089/history")
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"


def test_unpadded_local_id_is_accepted(client_factory) -> None:  # type: ignore[no-untyped-def]
    artwork = FakeResult(rows=[_fake_artwork_row("089")])
    variants = FakeResult(rows=[_fake_variant_row("jp-sv2a-089", "normal")])
    client, _ = client_factory([artwork, variants])
    resp = client.get("/jp/cards/SV2A/89")
    assert resp.status_code == 200
    assert resp.json()["local_id"] == "089"


def test_spread_from_mv(client_factory) -> None:  # type: ignore[no-untyped-def]
    resolve = _fake_card_scalars("normal")
    spread_rows = FakeResult(
        rows=[
            {
                "card_id": "jp-sv2a-089-normal",
                "condition": "NM",
                "cardrush_floor": 500,
                "snkrdunk_median_7d": 450.0,
                "spread_jpy": 50.0,
                "spread_pct": 0.111,
            }
        ]
    )
    client, _ = client_factory([resolve, spread_rows])
    resp = client.get("/jp/cards/SV2A/089/spread")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["cardrush_floor"] == 500
    assert rows[0]["spread_pct"] == pytest.approx(0.111)


def test_prices_400_for_unknown_variant_with_available_list(client_factory) -> None:  # type: ignore[no-untyped-def]
    # _resolve_card now fetches all variants in a single query.
    all_cards = FakeResult(
        rows=[
            {"variant": "normal", "card_id": "jp-sv2a-089-normal",
             "set_code": "SV2A", "local_id": "089"},
            {"variant": "master_ball_mirror", "card_id": "jp-sv2a-089-mbm",
             "set_code": "SV2A", "local_id": "089"},
        ]
    )
    client, _ = client_factory([all_cards])
    resp = client.get("/jp/cards/SV2A/089/prices?variant=bogus")
    assert resp.status_code == 400
    assert "available variants" in resp.json()["detail"]


def test_prices_404_when_artwork_missing(client_factory) -> None:  # type: ignore[no-untyped-def]
    # Single query returns no prints → 404.
    client, _ = client_factory([FakeResult(scalars=[])])
    resp = client.get("/jp/cards/SV2A/999/prices")
    assert resp.status_code == 404


# --- Graded prices / history ---------------------------------------------


def test_graded_prices_returns_list(client_factory) -> None:  # type: ignore[no-untyped-def]
    now = datetime(2025, 4, 1, tzinfo=UTC)
    resolve = _fake_card_scalars("normal")
    graded_rows = FakeResult(
        rows=[
            {
                "grade_company": "PSA",
                "grade_score": 10.0,
                "source": "cardrush",
                "price_jpy": 95000,
                "observed_at": now,
            }
        ]
    )
    client, _ = client_factory([resolve, graded_rows])
    resp = client.get("/jp/cards/SV2A/089/graded-prices")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["grade_company"] == "PSA"
    assert data[0]["grade_score"] == 10.0
    assert data[0]["price_jpy"] == 95000
    assert data[0]["source"] == "cardrush"


def test_graded_prices_empty(client_factory) -> None:  # type: ignore[no-untyped-def]
    resolve = _fake_card_scalars("normal")
    graded_rows = FakeResult(rows=[])
    client, _ = client_factory([resolve, graded_rows])
    resp = client.get("/jp/cards/SV2A/089/graded-prices")
    assert resp.status_code == 200
    assert resp.json() == []


def test_graded_prices_no_store_cache(client_factory) -> None:  # type: ignore[no-untyped-def]
    resolve = _fake_card_scalars("normal")
    graded_rows = FakeResult(rows=[])
    client, _ = client_factory([resolve, graded_rows])
    resp = client.get("/jp/cards/SV2A/089/graded-prices")
    assert resp.headers["Cache-Control"] == "no-store"


def test_graded_history_empty(client_factory) -> None:  # type: ignore[no-untyped-def]
    resolve = _fake_card_scalars("normal")
    history_rows = FakeResult(scalars=[])
    client, _ = client_factory([resolve, history_rows])
    resp = client.get("/jp/cards/SV2A/089/graded-history")
    assert resp.status_code == 200
    assert resp.json() == []


def test_graded_history_no_store_cache(client_factory) -> None:  # type: ignore[no-untyped-def]
    resolve = _fake_card_scalars("normal")
    history_rows = FakeResult(scalars=[])
    client, _ = client_factory([resolve, history_rows])
    resp = client.get("/jp/cards/SV2A/089/graded-history")
    assert resp.headers["Cache-Control"] == "no-store"


def test_graded_history_company_filter_accepted(client_factory) -> None:  # type: ignore[no-untyped-def]
    resolve = _fake_card_scalars("normal")
    history_rows = FakeResult(scalars=[])
    client, _ = client_factory([resolve, history_rows])
    resp = client.get("/jp/cards/SV2A/089/graded-history?company=PSA")
    assert resp.status_code == 200


def test_graded_history_days_param_accepted(client_factory) -> None:  # type: ignore[no-untyped-def]
    resolve = _fake_card_scalars("normal")
    history_rows = FakeResult(scalars=[])
    client, _ = client_factory([resolve, history_rows])
    resp = client.get("/jp/cards/SV2A/089/graded-history?days=30")
    assert resp.status_code == 200


def test_graded_prices_404_for_missing_card(client_factory) -> None:  # type: ignore[no-untyped-def]
    client, _ = client_factory([FakeResult(scalars=[])])
    resp = client.get("/jp/cards/SV2A/999/graded-prices")
    assert resp.status_code == 404


# --- Locale --------------------------------------------------------------


def test_unsupported_lang_returns_404(client_factory) -> None:  # type: ignore[no-untyped-def]
    client, session = client_factory([])
    resp = client.get("/xx/sets")
    assert resp.status_code == 404
    assert session.calls == []
