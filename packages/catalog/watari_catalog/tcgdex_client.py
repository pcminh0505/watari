"""Thin async wrapper around TCGdex public JSON API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.tcgdex.net/v2"


class TcgdexClient:
    def __init__(
        self,
        *,
        language: str = "ja",
        timeout_sec: float = 20.0,
        request_delay_sec: float = 0.25,
    ) -> None:
        self._language = language
        self._timeout = timeout_sec
        self._delay = request_delay_sec
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> TcgdexClient:
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _require(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("TcgdexClient used outside of `async with`")
        return self._client

    async def _get(self, path: str) -> Any | None:
        client = self._require()
        url = f"{BASE_URL}/{self._language}{path}"
        resp = await client.get(url)
        if resp.status_code == 404:
            logger.debug("tcgdex 404: %s", url)
            return None
        resp.raise_for_status()
        await asyncio.sleep(self._delay)
        return resp.json()

    async def get_all_sets(self) -> list[dict[str, Any]]:
        """Return the TCGdex set list (each entry includes ``cardCount``)."""
        data = await self._get("/sets")
        return data if isinstance(data, list) else []

    async def get_set(self, set_id: str) -> dict[str, Any] | None:
        """Return full set payload (incl. card list) or ``None`` on 404."""
        return await self._get(f"/sets/{set_id}")

    async def get_card(self, set_id: str, local_id: str) -> dict[str, Any] | None:
        """Return full per-card payload or ``None`` on 404."""
        return await self._get(f"/cards/{set_id}-{local_id}")
