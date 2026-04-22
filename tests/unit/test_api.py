"""Unit tests for the FastAPI read-side app (packages/api).

The tests use FastAPI's dependency-override mechanism to swap the real
``AsyncSession`` for a canned fake, so they never touch Postgres or the
materialized views. That keeps them fast and makes them the only regression
harness the API layer needs until we add real integration tests.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterable
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pokeprice_api.auth import AuthContext
from pokeprice_api.deps import get_session
from pokeprice_api.main import create_app
from pokeprice_api.ratelimit import rate_limit_dep
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

    # scalars() path (used by select(Model) returning ORM instances)
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

    # text()/mappings() path
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
    """Replacement for ``rate_limit_dep`` that always admits as anonymous.

    The auth/ratelimit specifics have their own test files; endpoint-shape
    tests don't care about them and would otherwise need Redis.
    """
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


# --- Healthz -------------------------------------------------------------


def test_healthz_returns_ok() -> None:
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# --- /sets ---------------------------------------------------------------


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


def test_list_sets_returns_all(client_factory) -> None:  # type: ignore[no-untyped-def]
    rows = [_fake_set_row("SV2A"), _fake_set_row("M2A", era="me")]
    client, _ = client_factory([FakeResult(scalars=rows)])
    resp = client.get("/sets")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert {d["set_code"] for d in data} == {"SV2A", "M2A"}


def test_list_sets_filters_by_era(client_factory) -> None:  # type: ignore[no-untyped-def]
    rows = [_fake_set_row("M2A", era="me")]
    client, session = client_factory([FakeResult(scalars=rows)])
    resp = client.get("/sets?era=me")
    assert resp.status_code == 200
    assert [d["set_code"] for d in resp.json()] == ["M2A"]
    # sanity: the statement we executed was a Select
    stmt, _ = session.calls[0]
    assert isinstance(stmt, Select)


def test_get_set_404_when_missing(client_factory) -> None:  # type: ignore[no-untyped-def]
    client, _ = client_factory([FakeResult(scalar=None)])
    resp = client.get("/sets/NOPE")
    assert resp.status_code == 404


def test_get_set_returns_row(client_factory) -> None:  # type: ignore[no-untyped-def]
    row = _fake_set_row("SV2A")
    client, _ = client_factory([FakeResult(scalar=row)])
    resp = client.get("/sets/SV2A")
    assert resp.status_code == 200
    assert resp.json()["set_code"] == "SV2A"


# --- /sets/{set_code}/cards + /cards/{card_id} ---------------------------


def _fake_card_row(local_id: str, variant: str = "normal") -> dict[str, Any]:
    now = datetime(2025, 1, 1, tzinfo=UTC)
    return {
        "card_id": f"jp-sv2a-{local_id}-{variant}",
        "artwork_id": f"jp-sv2a-{local_id}",
        "set_code": "SV2A",
        "local_id": local_id,
        "variant": variant,
        "is_tracked": True,
        "source_refs": {},
        "created_at": now,
        "updated_at": now,
        "name_ja": "ベトベトン",
        "name_en": "Muk",
        "rarity_code": "U",
        "image_url": "https://example.com/muk.png",
        "illustrator": None,
        "category": "card",
    }


def test_list_cards_for_set_denormalizes(client_factory) -> None:  # type: ignore[no-untyped-def]
    # first call: set existence check; second: the card rows
    set_exists = FakeResult(scalar="SV2A")
    cards = FakeResult(rows=[_fake_card_row("089"), _fake_card_row("089", "master_ball_mirror")])
    client, _ = client_factory([set_exists, cards])
    resp = client.get("/sets/SV2A/cards")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["name_ja"] == "ベトベトン"
    assert data[0]["rarity_code"] == "U"
    # variant is preserved in the response
    assert {d["variant"] for d in data} == {"normal", "master_ball_mirror"}


def test_list_cards_404_for_unknown_set(client_factory) -> None:  # type: ignore[no-untyped-def]
    client, _ = client_factory([FakeResult(scalar=None)])
    resp = client.get("/sets/NOPE/cards")
    assert resp.status_code == 404


def test_get_card_by_id(client_factory) -> None:  # type: ignore[no-untyped-def]
    row = _fake_card_row("089")
    client, _ = client_factory([FakeResult(rows=[row])])
    resp = client.get("/cards/jp-sv2a-089-normal")
    assert resp.status_code == 200
    body = resp.json()
    assert body["card_id"] == "jp-sv2a-089-normal"
    assert body["artwork_id"] == "jp-sv2a-089"


def test_get_card_404(client_factory) -> None:  # type: ignore[no-untyped-def]
    client, _ = client_factory([FakeResult(rows=[])])
    resp = client.get("/cards/jp-sv2a-999-normal")
    assert resp.status_code == 404


# --- prices / spread -----------------------------------------------------


def test_latest_prices_from_mv(client_factory) -> None:  # type: ignore[no-untyped-def]
    exists = FakeResult(scalar="jp-sv2a-089-normal")
    now = datetime(2025, 4, 1, tzinfo=UTC)
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
    client, _ = client_factory([exists, mv_rows])
    resp = client.get("/cards/jp-sv2a-089-normal/prices")
    assert resp.status_code == 200
    prices = resp.json()
    assert len(prices) == 2
    assert {p["source"] for p in prices} == {"cardrush", "snkrdunk"}


def test_prices_404_when_card_missing(client_factory) -> None:  # type: ignore[no-untyped-def]
    client, _ = client_factory([FakeResult(scalar=None)])
    resp = client.get("/cards/jp-xxx-001-normal/prices")
    assert resp.status_code == 404


def test_spread_from_mv(client_factory) -> None:  # type: ignore[no-untyped-def]
    exists = FakeResult(scalar="jp-sv2a-089-normal")
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
    client, _ = client_factory([exists, spread_rows])
    resp = client.get("/cards/jp-sv2a-089-normal/spread")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["cardrush_floor"] == 500
    assert rows[0]["spread_pct"] == pytest.approx(0.111)
