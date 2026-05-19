"""Unit tests for the FastAPI read-side app — online mode (no database)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from watari_api.auth import AuthContext
from watari_api.catalog_mem import MemArtwork, MemCatalog, MemSet, MemVariant
from watari_api.deps import get_catalog, get_price_proxy, get_session
from watari_api.main import create_app
from watari_api.price_proxy import PriceProxy
from watari_api.ratelimit import rate_limit_dep

# ---------------------------------------------------------------------------
# Fake catalog
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 1, 1, tzinfo=UTC)
_TODAY = date(2025, 1, 1)


def _fake_set(
    set_code: str = "SV2A",
    era: str = "sv",
    release_date: date | None = _TODAY,
) -> MemSet:
    return MemSet(
        set_code=set_code,
        era_block=era,
        language="jp",
        name_ja="ポケモンカード151",
        name_en="Pokemon Card 151",
        release_date=release_date,
        total=210,
        parent_set_code=None,
        tcgdex_id="sv2a",
        source_refs={},
        loaded_at=_NOW,
    )


def _fake_artwork(
    set_code: str = "SV2A",
    local_id: str = "089",
    variants: list[str] | None = None,
    rarity: str = "U",
    release_date: date | None = _TODAY,
) -> MemArtwork:
    vlist = variants or ["normal"]
    aid = f"jp-{set_code.lower()}-{local_id}"
    return MemArtwork(
        artwork_id=aid,
        set_code=set_code,
        local_id=local_id,
        name_ja="ベトベトン",
        name_en="Muk",
        rarity_code=rarity,
        image_url="https://example.com/muk.png",
        illustrator=None,
        category="card",
        language="jp",
        variants=[
            MemVariant(variant=v, card_id=f"{aid}-{v}", is_tracked=True) for v in vlist
        ],
        set_name_ja="ポケモンカード151",
        set_name_en="Pokemon Card 151",
        set_release_date=release_date,
    )


class FakeMemCatalog:
    """Thin fake MemCatalog for tests — backed by dicts, not YAML files."""

    def __init__(
        self,
        sets: list[MemSet] | None = None,
        artworks: list[MemArtwork] | None = None,
    ) -> None:
        self._sets = {s.set_code.upper(): s for s in (sets or [])}
        self._artworks: dict[tuple[str, str], MemArtwork] = {}
        self._artworks_by_set: dict[str, list[MemArtwork]] = {}
        for a in artworks or []:
            self._artworks[(a.set_code.upper(), a.local_id)] = a
            self._artworks_by_set.setdefault(a.set_code.upper(), []).append(a)

    def get_sets(self, *, language: str = "jp", era: str | None = None) -> list[MemSet]:
        rows = [s for s in self._sets.values() if s.language == language]
        if era is not None:
            rows = [s for s in rows if s.era_block == era.lower()]
        return rows

    def get_set(self, set_code: str, *, language: str = "jp") -> MemSet | None:
        s = self._sets.get(set_code.upper())
        if s is None or s.language != language:
            return None
        return s

    def get_artworks(self, set_code: str) -> list[MemArtwork]:
        return list(self._artworks_by_set.get(set_code.upper(), []))

    def get_artwork(self, set_code: str, local_id: str) -> MemArtwork | None:
        from watari_core.catalog import pad_local_id
        return self._artworks.get((set_code.upper(), pad_local_id(local_id)))

    def search_artworks(
        self,
        *,
        language: str = "jp",
        q: str | None = None,
        set_code: str | None = None,
        rarity: str | None = None,
        illustrator: str | None = None,
    ) -> list[MemArtwork]:
        results = [a for a in self._artworks.values() if a.language == language]
        if set_code is not None:
            results = [a for a in results if a.set_code.upper() == set_code.upper()]
        if rarity is not None:
            results = [a for a in results if a.rarity_code == rarity]
        if illustrator is not None:
            results = [a for a in results if a.illustrator == illustrator]
        if q is not None:
            from watari_core.catalog import pad_local_id
            q_lower = q.lower()
            q_padded = pad_local_id(q) if q.isdigit() else q
            results = [
                a for a in results
                if (a.name_ja and q_lower in a.name_ja.lower())
                or (a.name_en and q_lower in a.name_en.lower())
                or a.local_id == q_padded
                or a.set_code.upper() == q.upper()
            ]
        return results

    def get_rarities(self, *, language: str = "jp", set_code: str | None = None) -> list[str]:
        if set_code is not None:
            artworks = self.get_artworks(set_code)
        else:
            artworks = [a for a in self._artworks.values() if a.language == language]
        return sorted({a.rarity_code for a in artworks if a.rarity_code})


# ---------------------------------------------------------------------------
# Fake DB session
# ---------------------------------------------------------------------------


class FakeResult:
    """Minimal SQLAlchemy result stand-in for tests."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or []

    def mappings(self) -> "FakeResult":
        return self

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def __iter__(self):  # type: ignore[override]
        return iter(self._rows)


class FakeSession:
    """Fake AsyncSession for tests — returns preset rows for any execute()."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or []

    async def execute(self, stmt: Any, params: Any = None) -> FakeResult:
        return FakeResult(self._rows)


# ---------------------------------------------------------------------------
# Fake price proxy
# ---------------------------------------------------------------------------


class FakePriceProxy:
    """Fake PriceProxy for tests — returns pre-set Snkrdunk data."""

    def __init__(
        self,
        sd_prices: list[dict[str, Any]] | None = None,
        sd_market: int | None = None,
        graded: list[dict[str, Any]] | None = None,
        graded_hist: list[dict[str, Any]] | None = None,
    ) -> None:
        self._sd_prices = sd_prices or []
        self._sd_market = sd_market
        self._graded = graded or []
        self._graded_hist = graded_hist or []

    async def snkrdunk_latest_prices(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self._sd_prices

    async def snkrdunk_market_price(self, *args: Any, **kwargs: Any) -> int | None:
        return self._sd_market

    async def graded_prices(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self._graded

    async def graded_history(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self._graded_hist

    async def snkrdunk_raw_history(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


async def _anonymous_ratelimit() -> AuthContext:
    return AuthContext(
        authed=False, tier="free", api_key_id=None, key_prefix=None, identifier="ip:testclient"
    )


def _make_client(
    catalog: FakeMemCatalog | None = None,
    proxy: FakePriceProxy | None = None,
    session: FakeSession | None = None,
) -> TestClient:
    app = create_app()
    if catalog is not None:
        app.dependency_overrides[get_catalog] = lambda: catalog
    if proxy is not None:
        app.dependency_overrides[get_price_proxy] = lambda: proxy
    app.dependency_overrides[get_session] = lambda: (session or FakeSession())
    app.dependency_overrides[rate_limit_dep] = _anonymous_ratelimit
    return TestClient(app)


# ---------------------------------------------------------------------------
# Healthz
# ---------------------------------------------------------------------------


def test_healthz_returns_ok() -> None:
    app = create_app()
    app.dependency_overrides[rate_limit_dep] = _anonymous_ratelimit
    # Do not use context manager: lifespan now verifies DB connection and would
    # fail in CI where DATABASE_URL points to localhost (no DB running).
    # /healthz has no dependency on app.state so the lifespan is not needed.
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Sets
# ---------------------------------------------------------------------------


def test_list_sets_returns_all() -> None:
    catalog = FakeMemCatalog(sets=[_fake_set("SV2A"), _fake_set("M2A", era="me")])
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/sets")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert {d["set_code"] for d in data} == {"SV2A", "M2A"}


def test_list_sets_returns_total_count_header() -> None:
    catalog = FakeMemCatalog(sets=[_fake_set("SV2A")])
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/sets")
    assert resp.headers["X-Total-Count"] == "1"


def test_list_sets_returns_cache_header() -> None:
    catalog = FakeMemCatalog()
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/sets")
    assert "max-age=3600" in resp.headers["Cache-Control"]


def test_list_sets_filters_by_era() -> None:
    catalog = FakeMemCatalog(sets=[_fake_set("SV2A", era="sv"), _fake_set("M2A", era="me")])
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/sets?era=me")
    assert resp.status_code == 200
    assert [d["set_code"] for d in resp.json()] == ["M2A"]


def test_get_set_404_when_missing() -> None:
    catalog = FakeMemCatalog()
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/sets/NOPE")
    assert resp.status_code == 404


def test_get_set_returns_row() -> None:
    catalog = FakeMemCatalog(sets=[_fake_set("SV2A")])
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/sets/SV2A")
    assert resp.status_code == 200
    assert resp.json()["set_code"] == "SV2A"


def test_get_set_returns_cache_header() -> None:
    catalog = FakeMemCatalog(sets=[_fake_set("SV2A")])
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/sets/SV2A")
    assert "max-age=3600" in resp.headers["Cache-Control"]


def test_list_sets_total_value_jpy_is_none() -> None:
    # In online mode, total_value_jpy is always null — no per-set price aggregation.
    catalog = FakeMemCatalog(sets=[_fake_set("SV2A")])
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/sets")
    assert resp.json()[0]["total_value_jpy"] is None


def test_list_sets_sort_by_release_date_asc() -> None:
    old = _fake_set("OLD", release_date=date(2023, 1, 1))
    new = _fake_set("NEW", release_date=date(2024, 1, 1))
    catalog = FakeMemCatalog(sets=[old, new])
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/sets?sort=release_date&order=asc")
    codes = [d["set_code"] for d in resp.json()]
    assert codes.index("OLD") < codes.index("NEW")


def test_list_sets_sort_by_release_date_desc_nulls_last() -> None:
    dated = _fake_set("DATED", release_date=date(2024, 1, 1))
    undated = _fake_set("UNDATED", release_date=None)
    catalog = FakeMemCatalog(sets=[dated, undated])
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/sets?sort=release_date&order=desc")
    codes = [d["set_code"] for d in resp.json()]
    assert codes.index("DATED") < codes.index("UNDATED")


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------


def test_list_cards_for_set_returns_artwork_details() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089", variants=["normal", "master_ball_mirror"])],
    )
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/sets/SV2A/cards")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name_ja"] == "ベトベトン"
    # "normal" sorts first
    assert data[0]["variants"][0]["variant"] == "normal"


def test_list_cards_returns_total_count_header() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089")],
    )
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/sets/SV2A/cards")
    assert resp.headers["X-Total-Count"] == "1"


def test_list_cards_returns_cache_header() -> None:
    catalog = FakeMemCatalog(sets=[_fake_set("SV2A")])
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/sets/SV2A/cards")
    assert "max-age=3600" in resp.headers["Cache-Control"]


def test_list_cards_404_for_unknown_set() -> None:
    catalog = FakeMemCatalog()
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/sets/NOPE/cards")
    assert resp.status_code == 404


def test_get_card_by_set_and_local_id() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089")],
    )
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/SV2A/089")
    assert resp.status_code == 200
    body = resp.json()
    assert body["artwork_id"] == "jp-sv2a-089"
    assert body["variants"][0]["card_id"] == "jp-sv2a-089-normal"


def test_get_card_returns_cache_header() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089")],
    )
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/SV2A/089")
    assert "max-age=3600" in resp.headers["Cache-Control"]


def test_get_card_404() -> None:
    catalog = FakeMemCatalog(sets=[_fake_set("SV2A")])
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/SV2A/999")
    assert resp.status_code == 404


def test_unpadded_local_id_is_accepted() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089")],
    )
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/SV2A/89")
    assert resp.status_code == 200
    assert resp.json()["local_id"] == "089"


# ---------------------------------------------------------------------------
# Batch card lookup
# ---------------------------------------------------------------------------


def test_batch_full_code_found() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089")],
    )
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/batch?codes=sv2a+089%2F210")
    assert resp.status_code == 200
    item = resp.json()[0]
    assert item["error"] is None
    assert item["card"]["artwork_id"] == "jp-sv2a-089"
    assert item["candidates"] == []


def test_batch_full_code_not_found() -> None:
    catalog = FakeMemCatalog(sets=[_fake_set("SV2A")])
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/batch?codes=sv2a+999")
    assert resp.status_code == 200
    assert resp.json()[0]["error"] == "not_found"


def test_batch_id_only_returns_missing_set_code() -> None:
    catalog = FakeMemCatalog()
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/batch?codes=089")
    assert resp.status_code == 200
    assert resp.json()[0]["error"] == "missing_set_code"


def test_batch_fraction_only_returns_missing_set_code() -> None:
    catalog = FakeMemCatalog()
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/batch?codes=066%2F062")
    assert resp.json()[0]["error"] == "missing_set_code"


def test_batch_parse_error() -> None:
    catalog = FakeMemCatalog()
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/batch?codes=sv3a+%2F")
    assert resp.json()[0]["error"] == "parse_error"


def test_batch_mixed_found_and_not_found() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089")],
    )
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/batch?codes=sv2a+089,sv2a+999")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    found = next(d for d in data if d["input"] == "sv2a 089")
    missing = next(d for d in data if d["input"] == "sv2a 999")
    assert found["error"] is None
    assert found["card"]["artwork_id"] == "jp-sv2a-089"
    assert missing["error"] == "not_found"


def test_batch_fraction_notation_strips_denominator() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089")],
    )
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/batch?codes=sv2a+089%2F210")
    item = resp.json()[0]
    assert item["error"] is None
    assert item["card"]["local_id"] == "089"


def test_batch_empty_codes_returns_empty_list() -> None:
    catalog = FakeMemCatalog()
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/batch?codes=")
    assert resp.status_code == 200
    assert resp.json() == []


def test_batch_cache_header_set() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089")],
    )
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/batch?codes=sv2a+089")
    assert "max-age=3600" in resp.headers["Cache-Control"]


def test_batch_market_price_none_when_db_empty() -> None:
    # FakeSession returns no rows → market_price_jpy stays null.
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089")],
    )
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/batch?codes=sv2a+089")
    item = resp.json()[0]
    assert item["error"] is None
    assert item["market_price_jpy"] is None
    assert item["market_price_source_used"] is None


def test_post_batch_resolves_codes_from_json_body() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089")],
    )
    client = _make_client(catalog=catalog)
    resp = client.post("/jp/cards/batch", json={"codes": ["sv2a 089/210"]})
    assert resp.status_code == 200
    item = resp.json()[0]
    assert item["error"] is None
    assert item["card"]["artwork_id"] == "jp-sv2a-089"


def test_post_batch_empty_body_returns_empty_list() -> None:
    catalog = FakeMemCatalog()
    client = _make_client(catalog=catalog)
    resp = client.post("/jp/cards/batch", json={"codes": []})
    assert resp.status_code == 200
    assert resp.json() == []


def test_post_batch_missing_set_code() -> None:
    catalog = FakeMemCatalog()
    client = _make_client(catalog=catalog)
    resp = client.post("/jp/cards/batch", json={"codes": ["066/062"]})
    assert resp.json()[0]["error"] == "missing_set_code"


# ---------------------------------------------------------------------------
# Cards by sets
# ---------------------------------------------------------------------------


def test_by_sets_returns_cards() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089")],
    )
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/by-sets?codes=SV2A")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["artwork_id"] == "jp-sv2a-089"
    # market_price_jpy is always null in online mode
    assert data[0]["market_price_jpy"] is None


def test_by_sets_returns_total_count_header() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089")],
    )
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/by-sets?codes=SV2A")
    assert resp.headers["X-Total-Count"] == "1"


def test_by_sets_returns_cache_header() -> None:
    catalog = FakeMemCatalog(sets=[_fake_set("SV2A")])
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/by-sets?codes=SV2A")
    assert "max-age=3600" in resp.headers["Cache-Control"]


def test_by_sets_empty_codes_returns_empty() -> None:
    catalog = FakeMemCatalog()
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/by-sets?codes=")
    assert resp.status_code == 200
    assert resp.json() == []
    assert resp.headers["X-Total-Count"] == "0"


def test_by_sets_unknown_set_returns_empty() -> None:
    catalog = FakeMemCatalog()
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/by-sets?codes=NOPE")
    assert resp.status_code == 200
    assert resp.json() == []
    assert resp.headers["X-Total-Count"] == "0"


def test_post_by_sets_resolves_from_body() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089")],
    )
    client = _make_client(catalog=catalog)
    resp = client.post("/jp/cards/by-sets", json={"codes": ["SV2A"]})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_post_by_sets_empty_body_returns_empty() -> None:
    catalog = FakeMemCatalog()
    client = _make_client(catalog=catalog)
    resp = client.post("/jp/cards/by-sets", json={"codes": []})
    assert resp.status_code == 200
    assert resp.json() == []
    assert resp.headers["X-Total-Count"] == "0"


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def test_search_cards_matches_name_ja() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089")],
    )
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/search?q=ベト")
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["artwork_id"] == "jp-sv2a-089"
    # prices not embedded in search results
    assert body[0]["market_price_jpy"] is None


def test_search_cards_matches_local_id() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089")],
    )
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/search?q=089")
    assert resp.status_code == 200
    assert resp.json()[0]["local_id"] == "089"


def test_search_cards_matches_set_code() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "001")],
    )
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/search?q=sv2a")
    assert resp.status_code == 200
    assert resp.json()[0]["set_code"] == "SV2A"


def test_search_cards_filters_by_rarity() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089", rarity="SAR")],
    )
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/search?rarity=SAR")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp2 = client.get("/jp/cards/search?rarity=UR")
    assert len(resp2.json()) == 0


def test_search_cards_returns_total_count_header() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089")],
    )
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/search?q=ベト")
    assert resp.headers["X-Total-Count"] == "1"


def test_search_cards_rejects_blank_query() -> None:
    catalog = FakeMemCatalog()
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/search?q=%20%20%20")
    assert resp.status_code == 422


def test_list_card_rarities_returns_distinct_codes() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[
            _fake_artwork("SV2A", "001", rarity="AR"),
            _fake_artwork("SV2A", "002", rarity="SAR"),
            _fake_artwork("SV2A", "003", rarity="UR"),
        ],
    )
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/rarities")
    assert resp.status_code == 200
    assert resp.json() == ["AR", "SAR", "UR"]
    assert "max-age=3600" in resp.headers["Cache-Control"]


def test_list_card_rarities_filters_by_set_code() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089", rarity="U")],
    )
    client = _make_client(catalog=catalog)
    resp = client.get("/jp/cards/rarities?set_code=SV2A")
    assert resp.json() == ["U"]


# ---------------------------------------------------------------------------
# Prices / spread (via price proxy)
# ---------------------------------------------------------------------------


def _catalog_with_card(variant: str = "normal") -> FakeMemCatalog:
    return FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089", variants=[variant])],
    )


def test_latest_prices_returns_data() -> None:
    now = datetime(2025, 4, 1, tzinfo=UTC)
    # CR rows come from FakeSession; SD rows come from FakePriceProxy.snkrdunk_latest_prices
    session = FakeSession(rows=[
        {"source": "cardrush", "condition": "A", "price_jpy": 500, "stock_qty": 3, "observed_at": now},
    ])
    proxy = FakePriceProxy(
        sd_prices=[
            {"card_id": "jp-sv2a-089-normal", "source": "snkrdunk", "condition": "A",
             "price_jpy": 450, "stock_qty": None, "observed_at": now},
        ]
    )
    client = _make_client(catalog=_catalog_with_card(), proxy=proxy, session=session)
    resp = client.get("/jp/cards/SV2A/089/prices")
    assert resp.status_code == 200
    prices = resp.json()
    assert len(prices) == 2
    assert {p["source"] for p in prices} == {"cardrush", "snkrdunk"}


def test_latest_prices_returns_cache_header() -> None:
    client = _make_client(catalog=_catalog_with_card(), proxy=FakePriceProxy())
    resp = client.get("/jp/cards/SV2A/089/prices")
    assert resp.status_code == 200
    assert "max-age=1800" in resp.headers["Cache-Control"]


def test_history_returns_empty_from_fake_proxy() -> None:
    client = _make_client(catalog=_catalog_with_card(), proxy=FakePriceProxy())
    resp = client.get("/jp/cards/SV2A/089/history")
    assert resp.status_code == 200
    assert resp.json() == []
    assert resp.headers["Cache-Control"] == "public, max-age=1800, stale-while-revalidate=60"


def test_market_price_returns_data() -> None:
    # SD proxy returns 7d median → preferred over DB
    proxy = FakePriceProxy(sd_market=3500)
    client = _make_client(catalog=_catalog_with_card(), proxy=proxy)
    resp = client.get("/jp/cards/SV2A/089/market-price")
    assert resp.status_code == 200
    assert resp.json()["market_price_jpy"] == 3500
    assert resp.json()["source_used"] == "snkrdunk"


def test_market_price_404_when_no_data() -> None:
    # No SD data and FakeSession returns empty → 404
    proxy = FakePriceProxy(sd_market=None)
    client = _make_client(catalog=_catalog_with_card(), proxy=proxy)
    resp = client.get("/jp/cards/SV2A/089/market-price")
    assert resp.status_code == 404


def test_spread_returns_data() -> None:
    # CR floor from FakeSession; SD median from FakePriceProxy.snkrdunk_market_price
    session = FakeSession(rows=[{"cardrush_floor": 500}])
    proxy = FakePriceProxy(sd_market=550)
    client = _make_client(catalog=_catalog_with_card(), proxy=proxy, session=session)
    resp = client.get("/jp/cards/SV2A/089/spread")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["cardrush_floor"] == 500
    assert rows[0]["snkrdunk_median_7d"] == pytest.approx(550.0)
    assert rows[0]["spread_jpy"] == pytest.approx(50.0)


def test_prices_400_for_unknown_variant_with_available_list() -> None:
    catalog = _catalog_with_card(variant="normal")
    client = _make_client(catalog=catalog, proxy=FakePriceProxy())
    resp = client.get("/jp/cards/SV2A/089/prices?variant=bogus")
    assert resp.status_code == 400
    assert "available variants" in resp.json()["detail"]


def test_prices_404_when_artwork_missing() -> None:
    catalog = FakeMemCatalog(sets=[_fake_set("SV2A")])
    client = _make_client(catalog=catalog, proxy=FakePriceProxy())
    resp = client.get("/jp/cards/SV2A/999/prices")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Graded prices / history
# ---------------------------------------------------------------------------


def test_graded_prices_returns_list() -> None:
    now = datetime(2025, 4, 1, tzinfo=UTC)
    proxy = FakePriceProxy(
        graded=[{
            "grade_company": "PSA",
            "grade_score": 10.0,
            "source": "snkrdunk",
            "price_jpy": 95000,
            "observed_at": now,
        }]
    )
    client = _make_client(catalog=_catalog_with_card(), proxy=proxy)
    resp = client.get("/jp/cards/SV2A/089/graded-prices")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["grade_company"] == "PSA"
    assert data[0]["grade_score"] == 10.0
    assert data[0]["price_jpy"] == 95000


def test_graded_prices_empty() -> None:
    client = _make_client(catalog=_catalog_with_card(), proxy=FakePriceProxy())
    resp = client.get("/jp/cards/SV2A/089/graded-prices")
    assert resp.status_code == 200
    assert resp.json() == []


def test_graded_prices_no_store_cache() -> None:
    client = _make_client(catalog=_catalog_with_card(), proxy=FakePriceProxy())
    resp = client.get("/jp/cards/SV2A/089/graded-prices")
    assert resp.headers["Cache-Control"] == "no-store"


def test_graded_history_empty() -> None:
    client = _make_client(catalog=_catalog_with_card(), proxy=FakePriceProxy())
    resp = client.get("/jp/cards/SV2A/089/graded-history")
    assert resp.status_code == 200
    assert resp.json() == []


def test_graded_history_no_store_cache() -> None:
    client = _make_client(catalog=_catalog_with_card(), proxy=FakePriceProxy())
    resp = client.get("/jp/cards/SV2A/089/graded-history")
    assert resp.headers["Cache-Control"] == "no-store"


def test_graded_history_company_filter_accepted() -> None:
    client = _make_client(catalog=_catalog_with_card(), proxy=FakePriceProxy())
    resp = client.get("/jp/cards/SV2A/089/graded-history?company=PSA")
    assert resp.status_code == 200


def test_graded_history_days_param_accepted() -> None:
    client = _make_client(catalog=_catalog_with_card(), proxy=FakePriceProxy())
    resp = client.get("/jp/cards/SV2A/089/graded-history?days=30")
    assert resp.status_code == 200


def test_graded_prices_404_for_missing_card() -> None:
    catalog = FakeMemCatalog(sets=[_fake_set("SV2A")])
    client = _make_client(catalog=catalog, proxy=FakePriceProxy())
    resp = client.get("/jp/cards/SV2A/999/graded-prices")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Locale
# ---------------------------------------------------------------------------


def test_unsupported_lang_returns_404() -> None:
    catalog = FakeMemCatalog()
    client = _make_client(catalog=catalog)
    resp = client.get("/xx/sets")
    assert resp.status_code == 404
