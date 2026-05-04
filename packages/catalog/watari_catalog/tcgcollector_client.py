"""TCGCollector HTML client (www.tcgcollector.com).

This module is **audit-only** — it is *not* part of the live bootstrap
pipeline. Phase 2 of the data-quality audit uses it to populate the
sidecar oracle file ``packages/catalog/data/audit/<SET>.yml``. From there
``audit-diff`` (Phase 3) compares oracle vs. our YML truth, and Phase 5
applies the chosen fixes.

What we extract per card:

- ``name_en`` (from the ``<h1>``)
- ``rarity_raw`` (e.g. ``"Special Art Rare (SAR)"`` from the
  ``Rarity`` field of the card-info footer)
- ``illustrator`` (from the ``Illustrators`` field; may be ``"—"``)
- ``card_number`` (e.g. ``"190/190"``)
- ``expansion`` (e.g. ``"Shiny Treasure ex SV4a"``) — used to sanity-check
  we hit the right set.

What we do **not** extract: ``name_ja``. TCGCollector publishes only
the English/international name on JP cards, so JA-name backfill is the
job of the Phase-4 fallback oracle (``pokemon-card.com`` and the
``backfill_name_ja.py`` Pokellector JPN scraper).

Cloudflare: the site is behind a TLS-fingerprint check, so we use
``curl_cffi`` (Chrome impersonation) like the Cardrush client.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import random
import re
from datetime import UTC, datetime
from html import unescape
from typing import Any

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests
from watari_core.bronze import write_bronze_set

logger = logging.getLogger(__name__)


SOURCE = "tcgcollector"
BASE_URL = "https://www.tcgcollector.com"
DEFAULT_IMPERSONATE = "chrome124"
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Parsed data shapes
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class TcgCollectorIndexEntry:
    """One card discovered on a set's grid page."""

    card_id: str            # numeric ``data-card-id``, e.g. ``"43384"``
    detail_path: str        # ``/cards/43384/oddish-shiny-treasure-ex-001-190``
    title: str              # ``"Oddish (Shiny Treasure ex 001/190)"``
    local_id: str           # zero-padded ``"001"``
    set_total: str          # ``"190"`` (denominator)


@dataclasses.dataclass(frozen=True)
class TcgCollectorCardDetail:
    """Card-level fields extracted from a per-card detail page."""

    card_id: str
    name_en: str
    rarity_raw: str | None      # ``"Common (C)"`` or ``None`` if ``"—"``
    illustrator: str | None     # ``"Yuu Nishida"`` or ``None`` if ``"—"``
    card_number_raw: str        # ``"001/165"``
    expansion_raw: str          # ``"Pokémon Card 151 SV2a"``


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


_INDEX_LINK_RE = re.compile(r"^/cards/(\d+)/[a-z0-9-]+-(\d+)-(\d+)$")
# "Oddish (Shiny Treasure ex 001/190)"
_TITLE_RE = re.compile(r"^(?P<name>.+?)\s+\(.+?(?P<num>\d+)/(?P<total>\d+)\)\s*$")


def parse_set_index(html: str) -> list[TcgCollectorIndexEntry]:
    """Extract every card stub from a TCGCollector set page."""
    soup = BeautifulSoup(html, "lxml")
    entries: list[TcgCollectorIndexEntry] = []
    seen_card_ids: set[str] = set()

    grid = soup.select_one("#card-image-grid") or soup
    for tile in grid.select(".card-image-grid-item"):
        link = tile.select_one("a.card-image-grid-item-link")
        if link is None:
            continue
        href = (link.get("href") or "").strip()
        m = _INDEX_LINK_RE.match(href)
        if not m:
            continue
        card_id = m.group(1)
        local_id = m.group(2).zfill(3)
        set_total = m.group(3)

        title = unescape((link.get("title") or "").strip())

        # Avoid duplicates (TCGCollector renders some cards twice when both
        # 1st-edition and reprint are listed in the same set view).
        if card_id in seen_card_ids:
            continue
        seen_card_ids.add(card_id)

        entries.append(
            TcgCollectorIndexEntry(
                card_id=card_id,
                detail_path=href,
                title=title,
                local_id=local_id,
                set_total=set_total,
            )
        )
    return entries


def _footer_pairs(soup: BeautifulSoup) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in soup.select(".card-info-footer-item"):
        title_el = item.select_one(".card-info-footer-item-title")
        text_el = item.select_one(".card-info-footer-item-text-container")
        if not title_el or not text_el:
            continue
        label = title_el.get_text(strip=True)
        value = text_el.get_text(" ", strip=True)
        if label and value:
            out[label] = value
    return out


def _normalize_dash(value: str | None) -> str | None:
    """Treat the placeholder dash glyphs that TCGCollector uses as ``None``."""
    if value is None:
        return None
    stripped = value.strip()
    if stripped in ("", "—", "-", "–"):
        return None
    return stripped


def parse_card_detail(html: str, *, card_id: str) -> TcgCollectorCardDetail:
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.select_one("h1")
    name_en = h1.get_text(strip=True) if h1 else ""
    pairs = _footer_pairs(soup)
    return TcgCollectorCardDetail(
        card_id=card_id,
        name_en=name_en,
        rarity_raw=_normalize_dash(pairs.get("Rarity")),
        illustrator=_normalize_dash(pairs.get("Illustrators")),
        card_number_raw=pairs.get("Card number", ""),
        expansion_raw=pairs.get("Expansion", ""),
    )


# ---------------------------------------------------------------------------
# Async client
# ---------------------------------------------------------------------------


class TcgCollectorClient:
    """Polite async wrapper around ``curl_cffi`` for TCGCollector."""

    def __init__(
        self,
        *,
        impersonate: str = DEFAULT_IMPERSONATE,
        timeout_sec: float = 30.0,
        jitter_min: float = 1.2,
        jitter_max: float = 2.4,
        user_agent: str = DEFAULT_UA,
    ) -> None:
        self._impersonate = impersonate
        self._timeout = timeout_sec
        self._jitter_min = jitter_min
        self._jitter_max = jitter_max
        self._user_agent = user_agent
        self._session: Any = None

    def _ensure_session(self) -> Any:
        if self._session is None:
            self._session = curl_requests.Session(
                impersonate=self._impersonate,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        return self._session

    async def __aenter__(self) -> "TcgCollectorClient":
        self._ensure_session()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._session is not None:
            await asyncio.to_thread(self._session.close)
            self._session = None

    async def _sleep_jitter(self) -> None:
        delay = random.uniform(self._jitter_min, self._jitter_max)
        await asyncio.sleep(delay)

    async def _fetch(self, path_or_url: str) -> str:
        sess = self._ensure_session()
        url = (
            path_or_url
            if path_or_url.startswith("http")
            else f"{BASE_URL}{path_or_url}"
        )
        resp = await asyncio.to_thread(sess.get, url, timeout=self._timeout)
        if resp.status_code == 404:
            raise FileNotFoundError(f"tcgcollector: {url} -> 404")
        if resp.status_code != 200:
            raise RuntimeError(f"tcgcollector: {url} -> HTTP {resp.status_code}")
        return str(resp.text)

    # --- bronze-mirrored fetches -----------------------------------------

    async def fetch_set_index(
        self,
        *,
        set_id: str,
        slug: str,
        set_code: str,
        run_id: int,
        observed_at: datetime,
        bronze: bool = True,
    ) -> str:
        path = f"/sets/{set_id}/{slug}?cardSetType=anyCardVariant"
        html = await self._fetch(path)
        if bronze:
            write_bronze_set(
                source=SOURCE,
                set_code=set_code,
                run_id=run_id,
                observed_at=observed_at,
                payload=html,
                key_suffix=f"set-index/{set_id}-{slug}.html",
            )
        return html

    async def fetch_card_detail_html(
        self,
        *,
        detail_path: str,
        set_code: str,
        local_id: str,
        run_id: int,
        observed_at: datetime,
        bronze: bool = True,
    ) -> str:
        html = await self._fetch(detail_path)
        if bronze:
            write_bronze_set(
                source=SOURCE,
                set_code=set_code,
                run_id=run_id,
                observed_at=observed_at,
                payload=html,
                key_suffix=f"card-detail/{local_id}.html",
            )
        return html


# ---------------------------------------------------------------------------
# High-level orchestration helper used by ``audit-fetch``
# ---------------------------------------------------------------------------


async def fetch_full_set(
    client: TcgCollectorClient,
    *,
    set_id: str,
    slug: str,
    set_code: str,
    run_id: int,
    observed_at: datetime | None = None,
    detail_concurrency: int = 2,
    bronze: bool = True,
) -> tuple[list[TcgCollectorIndexEntry], dict[str, TcgCollectorCardDetail]]:
    """Fetch the set index plus every card-detail page.

    Returns ``(index_entries, {local_id_padded: detail})``. Cards whose
    detail fetches fail are logged but don't abort the run — partial
    coverage is still useful as audit data.
    """
    observed_at = observed_at or datetime.now(UTC)

    index_html = await client.fetch_set_index(
        set_id=set_id,
        slug=slug,
        set_code=set_code,
        run_id=run_id,
        observed_at=observed_at,
        bronze=bronze,
    )
    entries = parse_set_index(index_html)
    if not entries:
        logger.warning(
            "tcgcollector %s: set index returned no entries (id=%s slug=%s)",
            set_code,
            set_id,
            slug,
        )
        return entries, {}

    logger.info(
        "tcgcollector %s: %d entries on set index (id=%s)",
        set_code,
        len(entries),
        set_id,
    )

    sem = asyncio.Semaphore(max(1, detail_concurrency))
    details: dict[str, TcgCollectorCardDetail] = {}

    async def _one(entry: TcgCollectorIndexEntry) -> None:
        async with sem:
            try:
                html = await client.fetch_card_detail_html(
                    detail_path=entry.detail_path,
                    set_code=set_code,
                    local_id=entry.local_id,
                    run_id=run_id,
                    observed_at=observed_at,
                    bronze=bronze,
                )
            except Exception as exc:  # pragma: no cover - network-ish
                logger.warning(
                    "tcgcollector detail fetch failed %s/%s: %s",
                    set_code,
                    entry.local_id,
                    exc,
                )
                return
            try:
                detail = parse_card_detail(html, card_id=entry.card_id)
            except Exception as exc:
                logger.warning(
                    "tcgcollector detail parse failed %s/%s: %s",
                    set_code,
                    entry.local_id,
                    exc,
                )
                return
            details[entry.local_id] = detail
            # Polite pacing between detail fetches
            await client._sleep_jitter()

    # Run detail fetches sequentially within the semaphore-bounded gather
    await asyncio.gather(*[_one(e) for e in entries])
    return entries, details


__all__ = [
    "TcgCollectorClient",
    "TcgCollectorIndexEntry",
    "TcgCollectorCardDetail",
    "fetch_full_set",
    "parse_set_index",
    "parse_card_detail",
]
