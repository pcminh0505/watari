"""Cardrush HTTP client using ``curl_cffi`` to bypass Cloudflare.

Avoids launching a browser by impersonating a real Chrome TLS fingerprint.
Only used by the catalog layer — the price scraper package is deferred.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

logger = logging.getLogger(__name__)

BASE_URL = "https://www.cardrush-pokemon.jp"
SEARCH_PATH = "/product-list"
DEFAULT_IMPERSONATE = "chrome124"


@dataclass(frozen=True)
class CardrushListing:
    """A single product tile extracted from a search-results page."""

    name: str
    price_jpy: int | None
    stock_qty: int
    sold_out: bool
    external_url: str | None
    image_url: str | None


class CardrushClient:
    """Async wrapper around ``curl_cffi`` for paginated Cardrush search.

    Uses a worker thread via ``asyncio.to_thread`` — the curl_cffi API is sync.
    """

    def __init__(
        self,
        *,
        impersonate: str = DEFAULT_IMPERSONATE,
        proxy: str | None = None,
        timeout_sec: float = 30.0,
        jitter_min: float = 1.0,
        jitter_max: float = 2.5,
    ) -> None:
        self._impersonate = impersonate
        self._proxy = proxy or None
        self._timeout = timeout_sec
        self._jitter_min = jitter_min
        self._jitter_max = jitter_max
        self._session: Any = None

    def _ensure_session(self) -> Any:
        if self._session is None:
            kwargs: dict[str, Any] = {"impersonate": self._impersonate}
            if self._proxy:
                kwargs["proxies"] = {"http": self._proxy, "https": self._proxy}
            self._session = curl_requests.Session(**kwargs)
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            await asyncio.to_thread(self._session.close)
            self._session = None

    async def __aenter__(self) -> CardrushClient:
        self._ensure_session()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def _sleep_jitter(self) -> None:
        delay = random.uniform(self._jitter_min, self._jitter_max)
        await asyncio.sleep(delay)

    async def _fetch(self, url: str) -> str:
        sess = self._ensure_session()
        resp = await asyncio.to_thread(sess.get, url, timeout=self._timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"Cardrush {url} -> HTTP {resp.status_code}")
        return resp.text

    async def search_all_pages(
        self,
        keyword: str,
        *,
        max_pages: int = 50,
    ) -> list[tuple[int, str]]:
        """Fetch every page for a search keyword. Returns ``[(page_num, html), ...]``."""
        results: list[tuple[int, str]] = []
        from urllib.parse import quote

        page_num = 1
        while page_num <= max_pages:
            url = f"{BASE_URL}{SEARCH_PATH}?keyword={quote(keyword)}"
            if page_num > 1:
                url += f"&page={page_num}"
            logger.info("cardrush GET page=%d keyword=%r", page_num, keyword)
            html = await self._fetch(url)
            results.append((page_num, html))

            soup = BeautifulSoup(html, "lxml")
            if not soup.select_one(".item_data"):
                break
            if not _has_next_page(soup, page_num):
                break
            page_num += 1
            await self._sleep_jitter()

        return results


def _has_next_page(soup: BeautifulSoup, current_page: int) -> bool:
    target = f"page={current_page + 1}"
    for a in soup.select("a[href]"):
        if target in (a.get("href") or ""):
            return True
    return False


def parse_listings_from_html(html: str) -> list[CardrushListing]:
    """Extract raw product tiles from a Cardrush search-results page."""
    soup = BeautifulSoup(html, "lxml")
    rows: list[CardrushListing] = []

    for item in soup.select(".item_data"):
        name_el = item.select_one(".goods_name")
        if not name_el:
            continue
        name = name_el.get_text(strip=True)

        price_el = item.select_one(".figure")
        price_text = price_el.get_text(strip=True) if price_el else ""
        digits = "".join(ch for ch in price_text if ch.isdigit())
        price_jpy = int(digits) if digits else None

        stock_el = item.select_one(".stock")
        sold_out = False
        stock_qty = 0
        if stock_el is None:
            sold_out = True
        else:
            classes = stock_el.get("class") or []
            if "soldout" in classes:
                sold_out = True
            else:
                stock_digits = "".join(
                    ch for ch in stock_el.get_text(strip=True) if ch.isdigit()
                )
                stock_qty = int(stock_digits) if stock_digits else 0

        external_url: str | None = None
        link_el = item.select_one("a[href]")
        if link_el is not None:
            href = link_el.get("href") or ""
            if href.startswith("http"):
                external_url = href
            elif href:
                external_url = f"{BASE_URL}{href}"

        image_url: str | None = None
        img_el = item.select_one("img[src]")
        if img_el is not None:
            src = img_el.get("src") or ""
            if src.startswith("http"):
                image_url = src
            elif src:
                image_url = f"{BASE_URL}{src}"

        rows.append(
            CardrushListing(
                name=name,
                price_jpy=price_jpy,
                stock_qty=stock_qty,
                sold_out=sold_out,
                external_url=external_url,
                image_url=image_url,
            )
        )

    return rows
