"""Async HTTP client for SNKRDUNK's public apparels / sales-history endpoints."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

BASE_URL = "https://snkrdunk.com"
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {"User-Agent": DEFAULT_UA, "Accept": "application/json"}
SALES_PER_PAGE = 100
POLITE_DELAY_SEC = 0.25


class SnkrdunkClient:
    """Thin wrapper over SNKRDUNK's v1 API. One instance per scrape run."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
        polite_delay_sec: float = POLITE_DELAY_SEC,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=BASE_URL, headers=DEFAULT_HEADERS, timeout=timeout
        )
        self._polite_delay_sec = polite_delay_sec

    async def __aenter__(self) -> "SnkrdunkClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def resolve_apparel(self, era: str, local_id: str) -> dict[str, Any] | None:
        """Look up the apparel_id for a card by product number.

        Product number format: ``pkmn-tcg-{era}-{local_id}`` where ``local_id``
        is the part before any ``/`` (e.g. "183" from "183/165").
        """
        product_number = f"pkmn-tcg-{era}-{local_id.split('/')[0]}"
        resp = await self._client.get("/v1/apparels", params={"productNumber": product_number})
        resp.raise_for_status()
        data = resp.json()
        apparels = data.get("apparels") or []
        if not apparels:
            return None
        a = apparels[0]
        return {
            "apparel_id": int(a["id"]),
            "name": a.get("localizedName") or a.get("name", ""),
            "product_url": f"{BASE_URL}/apparels/{a['id']}",
            "raw": data,
        }

    async def fetch_sales_history(
        self,
        apparel_id: int,
        *,
        limit: int | None = None,
    ) -> tuple[list[dict[str, Any]], list[bytes]]:
        """Page through sales history.

        Returns (entries, raw_page_bodies). `raw_page_bodies` is a list of bytes
        (one per API page) so callers can write them to the bronze layer.
        """
        entries: list[dict[str, Any]] = []
        raw_pages: list[bytes] = []
        page = 1
        target = float("inf") if limit is None else limit

        while len(entries) < target:
            resp = await self._client.get(
                f"/v1/apparels/{apparel_id}/sales-history",
                params={"size_id": 0, "page": page, "per_page": SALES_PER_PAGE},
            )
            resp.raise_for_status()
            raw_pages.append(resp.content)
            data = resp.json()
            history = data.get("history") or []
            if not history:
                break
            for entry in history:
                entries.append(entry)
                if len(entries) >= target:
                    break
            if len(history) < SALES_PER_PAGE:
                break
            page += 1
            if self._polite_delay_sec:
                await asyncio.sleep(self._polite_delay_sec)

        return entries, raw_pages
