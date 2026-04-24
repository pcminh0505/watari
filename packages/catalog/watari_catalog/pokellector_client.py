"""Pokellector HTML client (jp.pokellector.com).

Pokellector is our *primary* catalog source for:

- high-resolution card image URLs (``den-cards.pokellector.com/{series_id}/...``),
- English card names (``Ethan's Pinsir``, ``Mewtwo``, …),
- rarity labels parsed from each card's detail page.

The client is plain ``httpx`` (no browser or Cloudflare bypass needed as of
2026-04). Every HTTP body is mirrored to MinIO under ``bronze/pokellector/...``
so a later re-bootstrap can run offline by reading the cache.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime

import httpx
from watari_core.bronze import write_bronze_set

logger = logging.getLogger(__name__)

BASE_URL = "https://jp.pokellector.com"
CARD_IMAGE_HOST = "https://den-cards.pokellector.com"
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
SOURCE = "pokellector"


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class PokellectorCardStub:
    """Minimum card data available from the set index page."""

    local_id: str              # "1", "150", "193" (not zero-padded)
    name_en: str               # "Ethan's Pinsir", "Mewtwo"
    slug: str                  # "Ethans-Pinsir-Card-1"
    pokellector_id: str        # "59914" (unique card id)
    series_id: str             # "427" (matches image subpath)
    image_slug: str            # "Ethans-Pinsir.M2A.1.59914"

    def image_url(self, size: str = "full") -> str:
        """``full`` for print resolution; ``thumb`` for the index preview."""
        suffix = ".thumb.png" if size == "thumb" else ".png"
        return f"{CARD_IMAGE_HOST}/{self.series_id}/{self.image_slug}{suffix}"

    def detail_path(self, set_slug: str) -> str:
        # Pokellector card detail URL: /{set_slug}/{card_slug}
        return f"/{set_slug}/{self.slug}"


@dataclasses.dataclass
class PokellectorSetIndex:
    set_slug: str                       # "M2A-MEGA-Dream-ex"
    name_en: str                        # "MEGA Dream ex"
    series_id: str | None               # "427"
    total_cards: int | None             # 193 (from card #N/T text)
    cards: list[PokellectorCardStub]


@dataclasses.dataclass
class PokellectorCardDetail:
    """Fields only available by fetching the individual card page."""

    local_id: str
    rarity_raw: str | None              # "Common", "Illustration Rare", ...
    set_total_raw: str | None           # "1/193" as seen on page


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


_SET_TITLE_RE = re.compile(
    # The set title is in an h1 with class="icon set", which wraps a logo
    # <img> followed by the plain-text set name.
    r'<h1[^>]*class="icon set"[^>]*>(?:\s*<img[^>]*>\s*)?([^<]+?)\s*</h1>',
    re.I,
)
# Anchor block that surrounds every card tile on the set index page. We
# require a `Card-\d+` suffix in href AND a `data-src="...M2A.1.59914..."` image
# so we only match actual cards, not pagination / "upcoming sets" blocks.
_CARD_BLOCK_RE = re.compile(
    r'<a\s+[^>]*?href="(?P<detail>/[^"]*?(?P<slug>[A-Za-z0-9\-]+?-Card-(?P<local_id>\d+)))"'
    r'[^>]*?title="(?P<title>[^"]+)"'
    r'[^>]*?>.*?'
    r'data-src="(?P<image>https?://den-cards\.pokellector\.com/'
    r'(?P<series>\d+)/(?P<image_slug>[^"]+?)\.thumb\.png)"',
    re.DOTALL,
)


def parse_set_index(html: str, set_slug: str) -> PokellectorSetIndex:
    """Extract every card stub from a jp.pokellector.com set page."""
    name_match = _SET_TITLE_RE.search(html)
    name_en = name_match.group(1).strip() if name_match else set_slug

    cards: list[PokellectorCardStub] = []
    series_id: str | None = None
    max_local = 0
    for m in _CARD_BLOCK_RE.finditer(html):
        image_slug = m.group("image_slug")
        # image_slug looks like "Ethans-Pinsir.M2A.1.59914" — the trailing
        # digits are Pokellector's unique card id.
        parts = image_slug.rsplit(".", 1)
        if len(parts) != 2:
            continue
        pokellector_id = parts[1]
        local_id = m.group("local_id")
        title = m.group("title")
        # Title comes as "Ethan's Pinsir - MEGA Dream ex #1". Strip everything
        # from the last " - " onwards.
        name_en_card = title.rsplit(" - ", 1)[0].strip()
        cards.append(
            PokellectorCardStub(
                local_id=local_id,
                name_en=name_en_card,
                slug=m.group("slug"),
                pokellector_id=pokellector_id,
                series_id=m.group("series"),
                image_slug=image_slug,
            )
        )
        series_id = m.group("series")
        max_local = max(max_local, int(local_id))

    # De-duplicate: some themes render each card twice in the DOM (once in a
    # "collection" block, once in the "view all" grid). Keep the first copy.
    seen: set[str] = set()
    deduped: list[PokellectorCardStub] = []
    for c in cards:
        if c.local_id in seen:
            continue
        seen.add(c.local_id)
        deduped.append(c)
    deduped.sort(key=lambda c: int(c.local_id))

    return PokellectorSetIndex(
        set_slug=set_slug,
        name_en=name_en,
        series_id=series_id,
        total_cards=max_local or None,
        cards=deduped,
    )


_RARITY_RE = re.compile(r"Rarity:\s*</strong>\s*([^<]+)", re.I)
_TOTAL_RE = re.compile(r'#card\d+">(\d+)/(\d+)')


def parse_card_detail(html: str, local_id: str) -> PokellectorCardDetail:
    """Extract rarity + total from a card detail page."""
    rarity = None
    m = _RARITY_RE.search(html)
    if m:
        rarity = m.group(1).strip()

    total_raw = None
    m = _TOTAL_RE.search(html)
    if m:
        total_raw = f"{m.group(1)}/{m.group(2)}"

    return PokellectorCardDetail(
        local_id=local_id, rarity_raw=rarity, set_total_raw=total_raw
    )


# ---------------------------------------------------------------------------
# Async client
# ---------------------------------------------------------------------------


class PokellectorClient:
    """HTTPX-based client with polite rate limiting and MinIO bronze caching."""

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        concurrency: int = 4,
        min_interval: float = 0.25,
        user_agent: str = DEFAULT_UA,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"User-Agent": user_agent, "Accept-Language": "ja,en;q=0.8"},
            timeout=timeout,
            follow_redirects=True,
        )
        self._sem = asyncio.Semaphore(concurrency)
        self._min_interval = min_interval
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> PokellectorClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def _throttle(self) -> None:
        async with self._lock:
            now = asyncio.get_event_loop().time()
            delta = now - self._last_request
            if delta < self._min_interval:
                await asyncio.sleep(self._min_interval - delta)
            self._last_request = asyncio.get_event_loop().time()

    async def _get(self, path: str) -> str:
        await self._throttle()
        async with self._sem:
            resp = await self._client.get(path)
            resp.raise_for_status()
            return resp.text

    # ---- bronze-cached fetches ------------------------------------------

    async def fetch_set_index(
        self,
        set_slug: str,
        *,
        set_code: str,
        run_id: int,
        observed_at: datetime,
        bronze: bool = True,
    ) -> str:
        """GET ``/{set_slug}/`` and optionally mirror to MinIO.

        ``set_slug`` is the short path without the leading ``/`` or trailing
        ``/`` (e.g. ``"Pokemon-151-Expansion"``).
        """
        html = await self._get(f"/{set_slug}/")
        if bronze:
            write_bronze_set(
                source=SOURCE,
                set_code=set_code,
                run_id=run_id,
                observed_at=observed_at,
                payload=html,
                key_suffix=f"set-index/{set_slug}.html",
            )
        return html

    async def fetch_card_detail(
        self,
        detail_path: str,
        *,
        set_code: str,
        local_id: str,
        run_id: int,
        observed_at: datetime,
        bronze: bool = True,
    ) -> str:
        html = await self._get(detail_path)
        if bronze:
            write_bronze_set(
                source=SOURCE,
                set_code=set_code,
                run_id=run_id,
                observed_at=observed_at,
                payload=html,
                key_suffix=f"card-detail/{local_id.zfill(3)}.html",
            )
        return html


# ---------------------------------------------------------------------------
# Convenience orchestrator used by bootstrap
# ---------------------------------------------------------------------------


async def fetch_full_set(
    client: PokellectorClient,
    *,
    set_code: str,
    set_slug: str,
    run_id: int,
    observed_at: datetime | None = None,
    detail_concurrency: int = 4,
    bronze: bool = True,
) -> tuple[PokellectorSetIndex, dict[str, PokellectorCardDetail]]:
    """Fetch the set index and every card's detail page.

    Returns ``(index, {local_id: detail})``. Missing detail pages are logged
    but don't abort the run.
    """
    observed_at = observed_at or datetime.now(UTC)

    index_html = await client.fetch_set_index(
        set_slug, set_code=set_code, run_id=run_id, observed_at=observed_at, bronze=bronze
    )
    index = parse_set_index(index_html, set_slug)
    logger.info(
        "pokellector %s: %d cards on set index (series_id=%s)",
        set_code,
        len(index.cards),
        index.series_id,
    )

    sem = asyncio.Semaphore(detail_concurrency)

    async def _one(card: PokellectorCardStub) -> tuple[str, PokellectorCardDetail | None]:
        async with sem:
            try:
                html = await client.fetch_card_detail(
                    card.detail_path(set_slug),
                    set_code=set_code,
                    local_id=card.local_id,
                    run_id=run_id,
                    observed_at=observed_at,
                    bronze=bronze,
                )
                return card.local_id, parse_card_detail(html, card.local_id)
            except Exception as exc:  # pragma: no cover - network-ish
                logger.warning(
                    "pokellector detail fetch failed %s %s: %s",
                    set_code,
                    card.local_id,
                    exc,
                )
                return card.local_id, None

    results: dict[str, PokellectorCardDetail] = {}
    for coro in asyncio.as_completed([_one(c) for c in index.cards]):
        local_id, detail = await coro
        if detail is not None:
            results[local_id] = detail
    return index, results


def card_image_url(card: PokellectorCardStub) -> str:
    """Return the full-resolution image URL for a card stub."""
    return card.image_url("full")


__all__ = [
    "PokellectorClient",
    "PokellectorCardStub",
    "PokellectorCardDetail",
    "PokellectorSetIndex",
    "fetch_full_set",
    "parse_set_index",
    "parse_card_detail",
    "card_image_url",
]


# Re-exports used in tests
_ = Iterable  # keep typing import load-bearing for type checkers
