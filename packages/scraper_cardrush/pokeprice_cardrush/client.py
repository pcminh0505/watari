"""Cardrush product-list fetcher using ``curl_cffi`` (Chrome TLS impersonation).

No browser, no Playwright. Presents a real Chrome TLS fingerprint so Cloudflare
lets us through. One session is reused across all pages of a scrape run.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, cast
from urllib.parse import quote

from curl_cffi import requests as curl_requests
from curl_cffi.requests.exceptions import RequestException, Timeout

from pokeprice_cardrush.retry import TransientError, with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://www.cardrush-pokemon.jp"
SEARCH_PATH = "/product-list"
DEFAULT_IMPERSONATE = "chrome124"


class CardrushClient:
    """Single-threaded ``curl_cffi`` wrapper for Cardrush search pages."""

    def __init__(
        self,
        *,
        impersonate: str = DEFAULT_IMPERSONATE,
        proxy: str | None = None,
        timeout_sec: float = 15.0,
        jitter_min_sec: float = 0.3,
        jitter_max_sec: float = 0.8,
        max_attempts: int = 3,
    ) -> None:
        self._impersonate = impersonate
        self._proxy = proxy or None
        self._timeout = timeout_sec
        self._jitter_min = jitter_min_sec
        self._jitter_max = jitter_max_sec
        self._max_attempts = max_attempts
        self._session: Any = None

    def _session_or_raise(self) -> Any:
        if self._session is None:
            kwargs: dict[str, Any] = {"impersonate": self._impersonate}
            if self._proxy:
                kwargs["proxies"] = {"http": self._proxy, "https": self._proxy}
            self._session = curl_requests.Session(**kwargs)
        return self._session

    async def __aenter__(self) -> CardrushClient:
        self._session_or_raise()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._session is not None:
            await asyncio.to_thread(self._session.close)
            self._session = None

    async def _sleep_jitter(self) -> None:
        delay = random.uniform(self._jitter_min, self._jitter_max)
        await asyncio.sleep(delay)

    async def _fetch_once(self, url: str) -> str:
        sess = self._session_or_raise()
        try:
            resp = await asyncio.to_thread(sess.get, url, timeout=self._timeout)
        except Timeout as exc:
            raise TransientError(f"timeout fetching {url}: {exc}") from exc
        except RequestException as exc:
            raise TransientError(f"request error on {url}: {exc}") from exc

        if resp.status_code >= 500:
            raise TransientError(f"HTTP {resp.status_code} on {url}")
        if resp.status_code != 200:
            raise RuntimeError(f"unexpected HTTP {resp.status_code} on {url}")
        return str(resp.text)

    async def fetch(self, url: str) -> str:
        """Fetch a URL with retry on transient errors."""
        return await with_retry(
            lambda: self._fetch_once(url),
            label=f"cardrush GET {url}",
            max_attempts=self._max_attempts,
        )

    @staticmethod
    def build_search_url(keyword: str, page: int = 1) -> str:
        url = f"{BASE_URL}{SEARCH_PATH}?keyword={quote(keyword)}"
        if page > 1:
            url += f"&page={page}"
        return url

    async def paginate(
        self,
        keyword: str,
        *,
        max_pages: int = 30,
    ) -> list[tuple[int, str, str]]:
        """Paginate a keyword search. Returns ``[(page_num, url, html), ...]``.

        Stop rules:
            1. A page returns no ``.item_data`` tiles (empty search result).
            2. A page's external product URLs are a subset of what we've already
               seen (Cardrush sometimes keeps returning the last page forever).
            3. Safety cap: ``max_pages``.
        """
        from bs4 import BeautifulSoup

        pages: list[tuple[int, str, str]] = []
        seen_product_urls: set[str] = set()

        for page_num in range(1, max_pages + 1):
            url = self.build_search_url(keyword, page=page_num)
            logger.info("GET keyword=%r page=%d", keyword, page_num)
            html = await self.fetch(url)

            soup = BeautifulSoup(html, "lxml")
            tiles = soup.select(".item_data")
            if not tiles:
                break

            fresh_urls: set[str] = set()
            for item in tiles:
                link_el = item.select_one("a[href]")
                if link_el is None:
                    continue
                href = cast(str, link_el.get("href") or "")
                if href:
                    fresh_urls.add(href)

            # stop rule 2: no new product URLs vs cumulative dedup set
            if fresh_urls and fresh_urls.issubset(seen_product_urls):
                logger.debug(
                    "keyword=%r page=%d has only duplicate product URLs; stopping",
                    keyword,
                    page_num,
                )
                break

            seen_product_urls.update(fresh_urls)
            pages.append((page_num, url, html))

            if page_num < max_pages:
                await self._sleep_jitter()

        return pages
