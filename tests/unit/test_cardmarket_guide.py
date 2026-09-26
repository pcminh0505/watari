"""CardmarketGuide: in-memory Cardmarket price guide keyed by our catalog."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from watari_api.cardmarket_guide import (
    RETRY_INTERVAL_SEC,
    CardmarketGuide,
    load_mappings,
)

_ROW = {
    "idProduct": 719531,
    "idCategory": 51,
    "avg": 0.97,
    "low": 0.02,
    "trend": 0.52,
    "avg1": 0.08,
    "avg7": 1.22,
    "avg30": 0.7,
    "avg-holo": 2.4,
    "low-holo": 0.15,
    "trend-holo": 3.85,
    "avg1-holo": 1.16,
    "avg7-holo": 1.54,
    "avg30-holo": 2.11,
}
_UNMAPPED = {**_ROW, "idProduct": 1}
_PAYLOAD = {"version": 1, "createdAt": "2026-09-26T02:42:01+0200", "priceGuides": [_ROW, _UNMAPPED]}


def _guide(row: dict[str, Any] | None = None) -> CardmarketGuide:
    guide = CardmarketGuide({("SV2A", "089"): 719531})
    guide.apply_guide({**_PAYLOAD, "priceGuides": [row or _ROW]})
    return guide


def test_load_mappings_reads_every_file(tmp_path: Path) -> None:
    (tmp_path / "SV2A.yml").write_text(
        "set_code: SV2A\nproducts:\n  '089': 719531\n  '205': 719658\n", encoding="utf-8"
    )
    (tmp_path / "M2A.yml").write_text("set_code: M2A\nproducts:\n  '1': 861245\n", encoding="utf-8")
    assert load_mappings(tmp_path) == {
        ("SV2A", "089"): 719531,
        ("SV2A", "205"): 719658,
        ("M2A", "001"): 861245,
    }


def test_load_mappings_missing_dir(tmp_path: Path) -> None:
    assert load_mappings(tmp_path / "nope") == {}


def test_apply_guide_keeps_only_mapped_products() -> None:
    guide = CardmarketGuide({("SV2A", "089"): 719531})
    assert guide.apply_guide(_PAYLOAD) == 1


def test_lookup_normal_uses_base_fields() -> None:
    price = _guide().lookup("sv2a", "89", "normal")
    assert price is not None
    assert price.id_product == 719531
    assert price.basis == "normal"
    assert price.price_eur == 0.52
    assert (price.trend_eur, price.avg7_eur, price.avg30_eur) == (0.52, 1.22, 0.7)
    assert price.url == (
        "https://www.cardmarket.com/en/Pokemon/Products?idProduct=719531&language=7&minCondition=2"
    )
    assert price.guide_date == datetime(2026, 9, 26, 0, 42, 1, tzinfo=UTC)


def test_lookup_mirror_variant_uses_holo_fields() -> None:
    price = _guide().lookup("SV2A", "089", "master_ball_mirror")
    assert price is not None
    assert price.basis == "mirror"
    assert (price.price_eur, price.avg7_eur, price.avg30_eur) == (3.85, 1.54, 2.11)


def test_headline_falls_back_to_avg30_when_trend_zero() -> None:
    price = _guide({**_ROW, "trend": 0}).lookup("SV2A", "089")
    assert price is not None
    assert price.trend_eur is None
    assert price.price_eur == 0.7


def test_headline_falls_back_to_avg7() -> None:
    price = _guide({**_ROW, "trend": None, "avg30": None}).lookup("SV2A", "089")
    assert price is not None
    assert price.price_eur == 1.22


def test_lookup_none_when_no_usable_value() -> None:
    row = {**_ROW, "trend-holo": 0, "avg7-holo": None, "avg30-holo": None}
    assert _guide(row).lookup("SV2A", "089", "poke_ball_mirror") is None


def test_lookup_none_before_first_download() -> None:
    assert CardmarketGuide({("SV2A", "089"): 719531}).lookup("SV2A", "089") is None


def test_lookup_none_when_unmapped_or_missing_from_guide() -> None:
    guide = CardmarketGuide({("SV2A", "089"): 719531, ("SV2A", "205"): 719658})
    guide.apply_guide(_PAYLOAD)
    assert guide.lookup("SV2A", "001") is None
    assert guide.lookup("SV2A", "205") is None


def test_apply_guide_rejects_empty_guide_and_keeps_last_good_data() -> None:
    guide = _guide()
    before = guide.lookup("SV2A", "089")
    assert before is not None
    before_date = guide._guide_date

    with pytest.raises(ValueError):
        guide.apply_guide(
            {"createdAt": "2026-09-27T00:00:00+0200", "priceGuides": []}
        )

    after = guide.lookup("SV2A", "089")
    assert after is not None
    assert after == before
    assert guide._guide_date == before_date


def test_ready_flips_after_apply_guide() -> None:
    guide = CardmarketGuide({("SV2A", "089"): 719531})
    assert guide.ready is False
    guide.apply_guide(_PAYLOAD)
    assert guide.ready is True


class _FakeResp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.content = json.dumps(payload).encode()

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self._result = result

    async def get(self, url: str) -> _FakeResp:
        if isinstance(self._result, Exception):
            raise self._result
        return _FakeResp(self._result)


async def test_refresh_downloads_and_applies() -> None:
    guide = CardmarketGuide({("SV2A", "089"): 719531})
    await guide.refresh(_FakeClient(_PAYLOAD))  # type: ignore[arg-type]
    assert guide.lookup("SV2A", "089") is not None


async def test_failed_refresh_keeps_last_good_data() -> None:
    guide = _guide()
    with pytest.raises(httpx.ConnectError):
        await guide.refresh(_FakeClient(httpx.ConnectError("down")))  # type: ignore[arg-type]
    assert guide.lookup("SV2A", "089") is not None


async def test_refresh_loop_retries_sooner_after_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    guide = CardmarketGuide({("SV2A", "089"): 719531})

    async def failing_refresh(client: Any) -> None:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(guide, "refresh", failing_refresh)
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await guide.run_refresh_loop(sleep=fake_sleep)
    assert delays == [RETRY_INTERVAL_SEC]


async def test_refresh_loop_is_noop_without_mappings() -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    # Returns immediately: no download attempt, no scheduling.
    await asyncio.wait_for(CardmarketGuide({}).run_refresh_loop(sleep=fake_sleep), timeout=1)
    assert sleeps == []


def test_load_mappings_reads_committed_cardmarket_maps() -> None:
    from watari_catalog.paths import cardmarket_dir

    mapping = load_mappings(cardmarket_dir())
    assert mapping
    assert mapping[("SV2A", "205")] == 719658


def test_load_mappings_drops_ids_shared_by_several_cards(tmp_path: Path) -> None:
    (tmp_path / "SV9A.yml").write_text(
        "set_code: SV9A\nproducts:\n  '002': 778391\n  '064': 778391\n  '010': 800001\n",
        encoding="utf-8",
    )
    (tmp_path / "SVP.yml").write_text(
        "set_code: SVP\nproducts:\n  '262': 800001\n  '100': 900001\n", encoding="utf-8"
    )
    assert load_mappings(tmp_path) == {("SVP", "100"): 900001}
