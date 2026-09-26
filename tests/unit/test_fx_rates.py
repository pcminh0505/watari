"""FX rate fetching: Frankfurter moved to api.frankfurter.dev and has no VND."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from watari_api import price_proxy
from watari_api.main import create_app

_URL = "https://api.frankfurter.dev/v1/latest"


class _FakeResp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def _patch_get(monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]], payload: Any) -> None:
    async def fake_get(self: httpx.AsyncClient, url: str, **kwargs: Any) -> _FakeResp:
        calls.append({"url": url, "params": kwargs.get("params")})
        if isinstance(payload, Exception):
            raise payload
        return _FakeResp(payload)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


def test_rates_endpoint_returns_usd_and_eur(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    _patch_get(monkeypatch, calls, {"rates": {"USD": 0.00635, "EUR": 0.00556}})
    resp = TestClient(create_app()).get("/rates")
    assert resp.status_code == 200
    assert resp.json() == {"USD": 0.00635, "EUR": 0.00556}
    assert calls == [{"url": _URL, "params": {"from": "JPY", "to": "USD,EUR"}}]


def test_rates_endpoint_502_when_upstream_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get(monkeypatch, [], httpx.ConnectError("down"))
    resp = TestClient(create_app()).get("/rates")
    assert resp.status_code == 502


async def test_proxy_fx_rates_use_new_host(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    _patch_get(monkeypatch, calls, {"rates": {"USD": 0.00635, "EUR": 0.00556}})
    rates = await price_proxy._do_fetch_fx_rates()
    assert rates == {"USD": 0.00635, "EUR": 0.00556}
    assert calls[0]["url"] == _URL


async def test_proxy_fx_rates_fall_back_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get(monkeypatch, [], httpx.ConnectError("down"))
    rates = await price_proxy._do_fetch_fx_rates()
    assert rates == price_proxy._FX_FALLBACK
