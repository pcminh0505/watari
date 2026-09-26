"""cardmarket-map: local_id → Cardmarket idProduct via TCGdex JP."""

from __future__ import annotations

from pathlib import Path

import yaml
from watari_catalog.cardmarket_map import (
    build_products,
    extract_id_product,
    read_mapping,
    render_mapping,
    resolve_tcgdex_id,
)


def test_resolve_tcgdex_id_uses_set_code() -> None:
    assert resolve_tcgdex_id("SV1S") == "SV1S"
    assert resolve_tcgdex_id("m2a") == "M2A"


def test_resolve_tcgdex_id_promo_override() -> None:
    assert resolve_tcgdex_id("SVP") == "SV-P"
    assert resolve_tcgdex_id("MP") == "M-P"


def test_extract_id_product() -> None:
    card = {"pricing": {"cardmarket": {"idProduct": 719658, "trend": 237.66}}}
    assert extract_id_product(card) == 719658
    assert extract_id_product(None) is None
    assert extract_id_product({"pricing": None}) is None
    assert extract_id_product({"pricing": {"cardmarket": {"idProduct": 0}}}) is None


def _fetcher(ids: dict[str, int | None], calls: list[str], fail: set[str] | None = None):
    async def fetch_id(local_id: str) -> int | None:
        calls.append(local_id)
        if fail and local_id in fail:
            raise RuntimeError("tcgdex down")
        return ids.get(local_id)

    return fetch_id


async def test_build_products_fetches_only_missing() -> None:
    calls: list[str] = []
    fetch = _fetcher({"002": 20}, calls)
    out = await build_products(["001", "002"], {"001": 10}, fetch, {10, 20})
    assert out == {"001": 10, "002": 20}
    assert calls == ["002"]


async def test_build_products_refresh_refetches_all_and_overrides() -> None:
    calls: list[str] = []
    fetch = _fetcher({"001": 11, "002": 20}, calls)
    out = await build_products(["001", "002"], {"001": 10}, fetch, {10, 11, 20}, refresh=True)
    assert out == {"001": 11, "002": 20}
    assert sorted(calls) == ["001", "002"]


async def test_build_products_drops_ids_not_in_catalog() -> None:
    fetch = _fetcher({"001": 999}, [])
    assert await build_products(["001"], {}, fetch, {10}) == {}


async def test_build_products_drops_stale_existing_entries() -> None:
    # "003" no longer has a card YAML; 55 is no longer a known product.
    fetch = _fetcher({}, [])
    out = await build_products(["001", "002"], {"001": 10, "002": 55, "003": 30}, fetch, {10, 30})
    assert out == {"001": 10}


async def test_build_products_survives_fetch_errors() -> None:
    fetch = _fetcher({"002": 20}, [], fail={"001"})
    assert await build_products(["001", "002"], {}, fetch, {20}) == {"002": 20}


def test_render_and_read_round_trip(tmp_path: Path) -> None:
    text = render_mapping(
        set_code="SV2A",
        tcgdex_id="sv2a",
        fetched_at="2026-09-26T10:00:00+00:00",
        artworks=3,
        products={"205": 719658, "089": 719531},
    )
    doc = yaml.safe_load(text)
    assert list(doc) == ["set_code", "source", "tcgdex_id", "fetched_at", "totals", "products"]
    assert doc["totals"] == {"artworks": 3, "mapped": 2}
    assert list(doc["products"]) == ["089", "205"]
    path = tmp_path / "SV2A.yml"
    path.write_text(text, encoding="utf-8")
    assert read_mapping(path) == {"089": 719531, "205": 719658}


def test_read_mapping_missing_file(tmp_path: Path) -> None:
    assert read_mapping(tmp_path / "NOPE.yml") == {}
