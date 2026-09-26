# Cardmarket EU Price Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every JP card a dedicated native-EUR Cardmarket price (detail page, gallery thumbnails, sortable lists), sourced from Cardmarket's free daily price guide.

**Architecture:** A catalog CLI command writes generated `packages/catalog/data/cardmarket/{SET}.yml` files (`local_id → idProduct`, taken from TCGdex JP). The API loads those maps at startup and a background task keeps Cardmarket's `price_guide_6.json` in memory (filtered to mapped products), so every lookup is an in-memory dict hit. Search/by-sets results embed `eu_price`; a new `/eu-price` endpoint serves per-variant values; the old per-card TCGdex Cardmarket path in `/international-prices` is removed.

**Tech Stack:** Python 3.13 · uv workspaces · FastAPI · Pydantic v2 · httpx · PyYAML · pytest (asyncio_mode=auto) · React 18 + TypeScript + React Query · bun.

**Spec:** `docs/superpowers/specs/2026-09-26-cardmarket-eu-price-design.md`

## Global Constraints

- Run Python tests with `uv run python -m pytest` (baseline: **404 passed**). Lint with `make lint` (ruff, line-length 100).
- FastAPI dependencies use `Annotated[..., Depends(...)]` aliases (ruff B008). Never add `Depends(rate_limit_dep)` to sub-routers.
- Mapping files are generated with PyYAML and never hand-edited.
- `EuPrice` never exposes Cardmarket's `low` (cheapest listing of any condition/language).
- `normal` variant → base price-guide fields; every non-`normal` variant → `*-holo` fields, `basis="mirror"`.
- Headline value `price_eur` = trend → avg30 → avg7; `0` and `null` both count as missing.
- Product link: `https://www.cardmarket.com/en/Pokemon/Products?idProduct={id}&language=7&minCondition=2` (form verified by the user in a browser).
- EU prices render in native € via `formatEUR`, never through `formatPrice`.
- Frontend check: `cd apps/web && bun run build` (tsc + vite). There is no frontend test runner.
- Commits: conventional (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`), no attribution trailer. Never stage `.cursor/`, `AGENTS.md`, or `plans/optimized-rolling-pebble.md`.

## Spec amendments (found while planning)

1. **FX rates are broken today.** `api.frankfurter.app` now 301-redirects to `api.frankfurter.dev/v1/latest`; httpx doesn't follow redirects, so `/rates` and `PriceProxy._do_fetch_fx_rates` always fail. Frankfurter also has no VND, so `/rates` 502s regardless. Task 1 fixes both (the € toggle depends on it).
2. **15 set YAMLs have an empty `tcgdex_id`** (all ME sets, CL, promos). TCGdex JP ids are case-insensitive and ME sets resolve under our set_code (`M2A-001` → `M2a-001`). Promo overrides: `SVP → SV-P`, `MP → M-P`. CL, SMPR, SP aren't on TCGdex.
3. **Product-id validation** uses every `idProduct` in `products_singles_6.json` (the file only contains category 51 "Pokémon Single").
4. **Link form verified:** `Products?idProduct=` resolves (spec §3.6 open item closed).

## File map

| File | Responsibility |
|---|---|
| `packages/api/watari_api/price_proxy.py` | Modify: Frankfurter URL constant; remove TCGdex Cardmarket code |
| `packages/api/watari_api/main.py` | Modify: `/rates` fix; lifespan loads `CardmarketGuide` + refresh task |
| `packages/catalog/watari_catalog/paths.py` | Modify: `cardmarket_dir()`, `cardmarket_yaml_path()` |
| `packages/catalog/watari_catalog/cardmarket_map.py` | Create: mapping builder + `run()` |
| `packages/catalog/watari_catalog/__main__.py` | Modify: `cardmarket-map` subcommand |
| `Makefile` | Modify: `catalog-cardmarket-map` target |
| `packages/api/watari_api/schemas.py` | Modify: `EuPrice`; `ArtworkSearchResult.eu_price` |
| `packages/api/watari_api/cardmarket_guide.py` | Create: mapping loader, guide store, lookup, refresh loop |
| `packages/api/watari_api/deps.py` | Modify: `get_cardmarket_guide` |
| `packages/api/watari_api/routers/cards.py` | Modify: embed `eu_price` in search + by-sets |
| `packages/api/watari_api/routers/prices.py` | Modify: `/eu-price`; `/international-prices` PriceCharting-only |
| `tests/unit/test_fx_rates.py` | Create |
| `tests/unit/test_cardmarket_map.py` | Create |
| `tests/unit/test_cardmarket_guide.py` | Create |
| `tests/unit/test_api.py` | Modify: `FakeCardmarketGuide`, new endpoint tests, intl changes |
| `apps/web/src/contexts/CurrencyContext.tsx`, `components/layout/CurrencyToggle.tsx`, `lib/formatters.ts` | Modify: EUR currency + `formatEUR` |
| `apps/web/src/types/api.ts`, `api/prices.ts` | Modify: `EuPrice` type, `useEuPrice` |
| `apps/web/src/components/prices/EuPriceCard.tsx` | Create |
| `apps/web/src/pages/CardDetailPage.tsx` | Modify: EU block |
| `apps/web/src/components/cards/CardThumbnail.tsx`, `SearchCardThumbnail.tsx` | Modify: `EU €x` line |
| `apps/web/src/components/cards/CardFilterBar.tsx`, `pages/CardsSearchPage.tsx`, `lib/sortSearchCards.ts` | Modify: EU sort keys |
| `packages/catalog/data/cardmarket/*.yml` | Generated (Task 8) |
| `CLAUDE.md`, spec doc | Modify (Task 9) |

---

### Task 1: Fix FX rates (Frankfurter host, EUR, no VND)

**Files:**
- Modify: `packages/api/watari_api/price_proxy.py` (constants block ~line 36; `_do_fetch_fx_rates` ~line 520)
- Modify: `packages/api/watari_api/main.py` (`/rates` handler ~line 132; imports)
- Test: `tests/unit/test_fx_rates.py`

**Interfaces:**
- Produces: `watari_api.price_proxy.FRANKFURTER_LATEST_URL: str`; `GET /rates` → `{"USD": float, "EUR": float}` (no VND; the web app supplies its own VND fallback in Task 6).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_fx_rates.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/unit/test_fx_rates.py -v`
Expected: `test_rates_endpoint_returns_usd_and_eur` and `test_proxy_fx_rates_use_new_host` FAIL (old URL `https://api.frankfurter.app/latest?...`, VND KeyError → 502).

- [ ] **Step 3: Implement**

In `price_proxy.py`, below `_FX_TTL = timedelta(hours=1)` add:

```python
# Frankfurter moved from api.frankfurter.app (now a 301) to this host.
# ECB data: has USD and EUR, but no VND.
FRANKFURTER_LATEST_URL = "https://api.frankfurter.dev/v1/latest"
```

Replace the request inside `_do_fetch_fx_rates`:

```python
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            resp = await client.get(
                FRANKFURTER_LATEST_URL,
                params={"from": "JPY", "to": "USD,EUR"},
            )
```

In `main.py`, change the import to `from watari_api.price_proxy import FRANKFURTER_LATEST_URL, PriceProxy` and replace the `/rates` handler body:

```python
    @app.get("/rates", tags=["utility"])
    async def exchange_rates() -> dict[str, float]:
        """Proxy JPY→USD/EUR exchange rates from Frankfurter.

        Runs server-side so the browser is never blocked by Frankfurter's
        missing CORS headers. Frankfurter (ECB data) has no VND; the web app
        keeps its own VND fallback.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                resp = await client.get(
                    FRANKFURTER_LATEST_URL, params={"from": "JPY", "to": "USD,EUR"}
                )
                resp.raise_for_status()
                rates = resp.json()["rates"]
            return {"USD": float(rates["USD"]), "EUR": float(rates["EUR"])}
        except Exception as exc:
            raise HTTPException(status_code=502, detail="exchange rate service unavailable") from exc
```

- [ ] **Step 4: Run tests**

Run: `uv run python -m pytest tests/unit/test_fx_rates.py -v && uv run python -m pytest`
Expected: 4 new PASS; full suite 408 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_fx_rates.py packages/api/watari_api/price_proxy.py packages/api/watari_api/main.py
git commit -m "fix(api): follow Frankfurter host move and serve EUR from /rates"
```

---

### Task 2: `cardmarket-map` command (idProduct mapping files)

**Files:**
- Modify: `packages/catalog/watari_catalog/paths.py` (append helpers; add `cardmarket/` to the module docstring tree)
- Create: `packages/catalog/watari_catalog/cardmarket_map.py`
- Modify: `packages/catalog/watari_catalog/__main__.py` (docstring, parser, dispatch)
- Modify: `Makefile` (`.PHONY` + target after `catalog-audit-rollout`)
- Test: `tests/unit/test_cardmarket_map.py`

**Interfaces:**
- Produces: `paths.cardmarket_dir() -> Path`, `paths.cardmarket_yaml_path(set_code: str) -> Path`; file format:
  ```yaml
  set_code: SV2A
  source: tcgdex
  tcgdex_id: sv2a
  fetched_at: '2026-09-26T10:00:00+00:00'
  totals: {artworks: 210, mapped: 210}
  products: {'089': 719531, '205': 719658}
  ```
  (block style in the actual file; `products` keys are padded `local_id` strings sorted ascending).
- Produces (tested): `resolve_tcgdex_id(set_code: str, tcgdex_id: str | None) -> str`, `extract_id_product(card: dict | None) -> int | None`, `read_mapping(path: Path) -> dict[str, int]`, `render_mapping(*, set_code, tcgdex_id, fetched_at, artworks, products) -> str`, `async build_products(local_ids, existing, fetch_id, valid_ids, *, refresh=False, concurrency=5) -> dict[str, int]`, `async run(*, sets: list[str] | None, refresh: bool = False, concurrency: int = 5) -> int`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_cardmarket_map.py`:

```python
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


def test_resolve_tcgdex_id_prefers_yaml_value() -> None:
    assert resolve_tcgdex_id("SV2A", "sv2a") == "sv2a"


def test_resolve_tcgdex_id_promo_override() -> None:
    assert resolve_tcgdex_id("SVP", None) == "SV-P"
    assert resolve_tcgdex_id("MP", "") == "M-P"


def test_resolve_tcgdex_id_falls_back_to_set_code() -> None:
    assert resolve_tcgdex_id("M2A", None) == "M2A"


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/unit/test_cardmarket_map.py -v`
Expected: collection ERROR — `ModuleNotFoundError: No module named 'watari_catalog.cardmarket_map'`.

- [ ] **Step 3: Implement paths helpers**

Append to `packages/catalog/watari_catalog/paths.py` (before `reports_dir`), and add a `└── cardmarket/  ← generated local_id → Cardmarket idProduct maps` line to the docstring tree:

```python
def cardmarket_dir() -> pathlib.Path:
    """Directory holding generated Cardmarket idProduct maps (one YML per set)."""
    return data_dir() / "cardmarket"


def cardmarket_yaml_path(set_code: str) -> pathlib.Path:
    """Path of a set's Cardmarket map, e.g. ``data/cardmarket/SV2A.yml``."""
    return cardmarket_dir() / f"{set_code.upper()}.yml"
```

- [ ] **Step 4: Implement `cardmarket_map.py`**

Create `packages/catalog/watari_catalog/cardmarket_map.py`:

```python
"""Build ``data/cardmarket/<SET>.yml``: local_id → Cardmarket idProduct.

TCGdex's JP card payload carries Cardmarket's product id under
``pricing.cardmarket.idProduct``. Cardmarket product names are not unique
within an expansion (SV2a has four "Mew ex" products), so this map is the
only reliable join between our catalog and Cardmarket's price guide.

Product ids are stable: by default only local_ids missing from the existing
file are fetched. ``--refresh`` re-fetches every card; a card whose fetch
yields nothing keeps its previous id.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from watari_catalog.paths import cardmarket_dir, cardmarket_yaml_path, cards_set_dir
from watari_catalog.seed_sets import load_sets_yaml
from watari_catalog.tcgdex_client import TcgdexClient

logger = logging.getLogger(__name__)

# Every entry in this file is a Pokémon single (idCategory 51).
PRODUCT_CATALOG_URL = (
    "https://downloads.s3.cardmarket.com/productCatalog/productList/products_singles_6.json"
)

# Sets without a YAML tcgdex_id whose TCGdex JP id differs from our set_code
# (our promo set_codes must stay hyphen-free; TCGdex's are hyphenated).
_TCGDEX_ID_OVERRIDE: dict[str, str] = {"SVP": "SV-P", "MP": "M-P"}

FetchId = Callable[[str], Awaitable[int | None]]


def resolve_tcgdex_id(set_code: str, tcgdex_id: str | None) -> str:
    """TCGdex JP set id: YAML value, else override, else set_code (ids are case-insensitive)."""
    code = set_code.upper()
    return tcgdex_id or _TCGDEX_ID_OVERRIDE.get(code, code)


def extract_id_product(card: dict[str, Any] | None) -> int | None:
    """``pricing.cardmarket.idProduct`` from a TCGdex card payload, if present."""
    if not card:
        return None
    cardmarket = (card.get("pricing") or {}).get("cardmarket") or {}
    pid = cardmarket.get("idProduct")
    return pid if isinstance(pid, int) and pid > 0 else None


def read_mapping(path: Path) -> dict[str, int]:
    """Existing ``products`` block of a map file, or ``{}`` if the file is absent."""
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): int(v) for k, v in (raw.get("products") or {}).items()}


def render_mapping(
    *,
    set_code: str,
    tcgdex_id: str,
    fetched_at: str,
    artworks: int,
    products: dict[str, int],
) -> str:
    doc = {
        "set_code": set_code,
        "source": "tcgdex",
        "tcgdex_id": tcgdex_id,
        "fetched_at": fetched_at,
        "totals": {"artworks": artworks, "mapped": len(products)},
        "products": {k: products[k] for k in sorted(products)},
    }
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


async def build_products(
    local_ids: list[str],
    existing: dict[str, int],
    fetch_id: FetchId,
    valid_ids: set[int],
    *,
    refresh: bool = False,
    concurrency: int = 5,
) -> dict[str, int]:
    """Return the complete local_id → idProduct map for one set.

    Existing entries survive only if the card still exists and the id is still
    a known Cardmarket product. Fetch errors are logged and skipped.
    """
    wanted = set(local_ids)
    products = {k: v for k, v in existing.items() if k in wanted and v in valid_ids}
    todo = local_ids if refresh else [lid for lid in local_ids if lid not in products]
    sem = asyncio.Semaphore(concurrency)

    async def one(local_id: str) -> tuple[str, int | None]:
        async with sem:
            try:
                return local_id, await fetch_id(local_id)
            except Exception:
                logger.warning("cardmarket-map: fetch failed for %s", local_id, exc_info=True)
                return local_id, None

    for local_id, pid in await asyncio.gather(*(one(lid) for lid in todo)):
        if pid is None:
            continue
        if pid not in valid_ids:
            logger.warning(
                "cardmarket-map: idProduct %s for %s is not a known Pokémon single; dropped",
                pid,
                local_id,
            )
            continue
        products[local_id] = pid
    return products


async def fetch_valid_product_ids(client: httpx.AsyncClient) -> set[int]:
    """All Pokémon single idProducts from Cardmarket's public product catalog."""
    resp = await client.get(PRODUCT_CATALOG_URL)
    resp.raise_for_status()
    return {int(p["idProduct"]) for p in resp.json().get("products") or []}


def _local_ids(set_code: str) -> list[str]:
    return sorted(p.stem for p in cards_set_dir(set_code).glob("*.yml"))


async def run(*, sets: list[str] | None, refresh: bool = False, concurrency: int = 5) -> int:
    rows = load_sets_yaml()
    if sets:
        wanted = {s.upper() for s in sets}
        unknown = wanted - {r["set_code"] for r in rows}
        if unknown:
            logger.error("cardmarket-map: unknown set code(s): %s", ", ".join(sorted(unknown)))
            return 1
        rows = [r for r in rows if r["set_code"] in wanted]

    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as http:
            valid_ids = await fetch_valid_product_ids(http)
    except Exception:
        logger.exception("cardmarket-map: could not download Cardmarket product catalog")
        return 1
    logger.info("cardmarket-map: %d known Cardmarket Pokémon singles", len(valid_ids))

    cardmarket_dir().mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(UTC).isoformat()
    async with TcgdexClient(language="ja", timeout_sec=15.0, request_delay_sec=0.0) as tcgdex:
        for row in rows:
            set_code = row["set_code"]
            local_ids = _local_ids(set_code)
            if not local_ids:
                logger.info("cardmarket-map: %s has no card YAMLs; skipped", set_code)
                continue
            tcgdex_id = resolve_tcgdex_id(set_code, row.get("tcgdex_id"))
            path = cardmarket_yaml_path(set_code)
            existing = read_mapping(path)

            async def fetch_id(local_id: str, _tid: str = tcgdex_id) -> int | None:
                return extract_id_product(await tcgdex.get_card(_tid, local_id))

            products = await build_products(
                local_ids, existing, fetch_id, valid_ids, refresh=refresh, concurrency=concurrency
            )
            if not products and not path.exists():
                logger.info(
                    "cardmarket-map: %s — no Cardmarket products via TCGdex %r; no file written",
                    set_code,
                    tcgdex_id,
                )
                continue
            if path.exists() and products == existing:
                logger.info("cardmarket-map: %s unchanged (%d mapped)", set_code, len(products))
                continue
            path.write_text(
                render_mapping(
                    set_code=set_code,
                    tcgdex_id=tcgdex_id,
                    fetched_at=fetched_at,
                    artworks=len(local_ids),
                    products=products,
                ),
                encoding="utf-8",
            )
            logger.info(
                "cardmarket-map: %s — %d/%d mapped → %s",
                set_code,
                len(products),
                len(local_ids),
                path,
            )
    return 0
```

- [ ] **Step 5: Wire the CLI and Makefile**

In `__main__.py` docstring, after the `audit-apply` entry add:

```
    cardmarket-map [--set SV2A ...] [--refresh] [--concurrency 5]
        Write ``data/cardmarket/<SET>.yml`` (local_id → Cardmarket idProduct,
        taken from TCGdex JP). Only unmapped cards are fetched unless
        ``--refresh``. No ``--set`` → every set.
```

In `_build_parser`, before `return p`:

```python
    cm = sub.add_parser(
        "cardmarket-map",
        help="Write data/cardmarket/<SET>.yml (local_id → Cardmarket idProduct via TCGdex JP)",
    )
    cm.add_argument("--set", dest="sets", action="append", default=None)
    cm.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch every card instead of only unmapped ones",
    )
    cm.add_argument("--concurrency", type=int, default=5)
```

In `_dispatch`, before the final `return 1`:

```python
    if args.command == "cardmarket-map":
        from watari_catalog import cardmarket_map

        return await cardmarket_map.run(
            sets=args.sets,
            refresh=args.refresh,
            concurrency=args.concurrency,
        )
```

In `Makefile`, add `catalog-cardmarket-map` to the `catalog-audit ...` `.PHONY` line, and after the `catalog-audit-rollout` target:

```make
# Cardmarket idProduct maps (TCGdex JP → data/cardmarket/<SET>.yml). Generated; don't hand-edit.
#         Usage: make catalog-cardmarket-map [SET=SV2A] [REFRESH=1]
catalog-cardmarket-map:
	uv run python -m watari_catalog cardmarket-map $(if $(SET),--set $(SET)) $(if $(REFRESH),--refresh)
```

- [ ] **Step 6: Run tests + smoke one set**

Run: `uv run python -m pytest tests/unit/test_cardmarket_map.py -v && uv run python -m pytest`
Expected: 11 new PASS; full suite 419 passed.

Run: `make catalog-cardmarket-map SET=SV2A`
Expected: log `SV2A — 210/210 mapped`; `packages/catalog/data/cardmarket/SV2A.yml` contains `'205': 719658`. Delete that file afterwards (`rm packages/catalog/data/cardmarket/SV2A.yml`) — the full backfill is committed in Task 8.

- [ ] **Step 7: Commit**

```bash
git add packages/catalog/watari_catalog/paths.py packages/catalog/watari_catalog/cardmarket_map.py packages/catalog/watari_catalog/__main__.py Makefile tests/unit/test_cardmarket_map.py
git commit -m "feat(catalog): add cardmarket-map command for Cardmarket idProduct maps"
```

---

### Task 3: `CardmarketGuide` in-memory price store + `EuPrice` schema

**Files:**
- Modify: `packages/api/watari_api/schemas.py` (imports; add `EuPrice` directly **above** `class ArtworkSearchResult`)
- Create: `packages/api/watari_api/cardmarket_guide.py`
- Test: `tests/unit/test_cardmarket_guide.py`

**Interfaces:**
- Consumes: `watari_catalog.paths.cardmarket_dir()` (Task 2).
- Produces: `watari_api.schemas.EuPrice`; `watari_api.cardmarket_guide.CardmarketGuide` with `CardmarketGuide(mapping: dict[tuple[str, str], int])`, `classmethod load() -> CardmarketGuide`, `apply_guide(payload: dict) -> int`, `lookup(set_code: str, local_id: str, variant: str = "normal") -> EuPrice | None`, `async refresh(client) -> None`, `async run_refresh_loop(*, sleep=asyncio.sleep) -> None`; module function `load_mappings(directory: Path) -> dict[tuple[str, str], int]`; constants `PRICE_GUIDE_URL`, `REFRESH_INTERVAL_SEC = 21600`, `RETRY_INTERVAL_SEC = 900`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_cardmarket_guide.py`:

```python
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
    await CardmarketGuide({}).run_refresh_loop()  # returns immediately
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/unit/test_cardmarket_guide.py -v`
Expected: collection ERROR — `ModuleNotFoundError: No module named 'watari_api.cardmarket_guide'`.

- [ ] **Step 3: Add the `EuPrice` schema**

In `schemas.py`, change `from typing import Any` to `from typing import Any, Literal`, then insert directly above `class ArtworkSearchResult`:

```python
class EuPrice(BaseModel):
    """Cardmarket price-guide values for one JP card, in native EUR.

    Source is Cardmarket's public daily price guide, which has no condition or
    language breakdown. Its ``low`` field (cheapest listing of *any* condition)
    is deliberately not exposed. ``basis="mirror"`` rows come from the
    reverse-holo fields, which combine Poké Ball and Master Ball mirrors.
    """

    id_product: int
    url: str  # product page pre-filtered to Japanese + Near Mint or better
    price_eur: float  # headline/sort value: trend → avg30 → avg7
    trend_eur: float | None = None
    avg7_eur: float | None = None
    avg30_eur: float | None = None
    basis: Literal["normal", "mirror"]
    guide_date: datetime
```

- [ ] **Step 4: Implement `cardmarket_guide.py`**

Create `packages/api/watari_api/cardmarket_guide.py`:

```python
"""Cardmarket EU prices for JP cards, served from memory.

Two inputs:

- ``data/cardmarket/<SET>.yml`` — generated ``local_id → idProduct`` maps
  (``python -m watari_catalog cardmarket-map``), loaded once at startup.
- Cardmarket's public daily price guide (``price_guide_6.json``, ~15 MB),
  downloaded by a background task and filtered to mapped products.

Lookups never do I/O. Until the first successful download they return None.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from watari_catalog.paths import cardmarket_dir
from watari_core.catalog import pad_local_id

from watari_api.schemas import EuPrice

logger = logging.getLogger(__name__)

PRICE_GUIDE_URL = (
    "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json"
)
REFRESH_INTERVAL_SEC = 6 * 60 * 60
RETRY_INTERVAL_SEC = 15 * 60

# Product page filtered to Japanese (language=7) and Near Mint or better (minCondition=2).
_PRODUCT_URL = (
    "https://www.cardmarket.com/en/Pokemon/Products?idProduct={id}&language=7&minCondition=2"
)

CardKey = tuple[str, str]  # (SET_CODE, padded local_id)


def load_mappings(directory: Path) -> dict[CardKey, int]:
    """Read every ``<SET>.yml`` map in ``directory`` into one lookup dict."""
    mapping: dict[CardKey, int] = {}
    if not directory.is_dir():
        return mapping
    for path in sorted(directory.glob("*.yml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        set_code = str(raw.get("set_code") or path.stem).upper()
        for local_id, pid in (raw.get("products") or {}).items():
            mapping[(set_code, pad_local_id(str(local_id)))] = int(pid)
    return mapping


def _eur(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


def _parse_created_at(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value)).astimezone(UTC)
    except ValueError:
        return datetime.now(UTC)


def build_eu_price(
    id_product: int, row: dict[str, Any], *, variant: str, guide_date: datetime
) -> EuPrice | None:
    """Pick base or reverse-holo fields for ``variant``; None if nothing usable."""
    mirror = variant != "normal"
    suffix = "-holo" if mirror else ""
    trend = _eur(row, f"trend{suffix}")
    avg7 = _eur(row, f"avg7{suffix}")
    avg30 = _eur(row, f"avg30{suffix}")
    headline = trend or avg30 or avg7
    if headline is None:
        return None
    return EuPrice(
        id_product=id_product,
        url=_PRODUCT_URL.format(id=id_product),
        price_eur=headline,
        trend_eur=trend,
        avg7_eur=avg7,
        avg30_eur=avg30,
        basis="mirror" if mirror else "normal",
        guide_date=guide_date,
    )


class CardmarketGuide:
    """Mapped Cardmarket price-guide rows, keyed by our (set_code, local_id)."""

    def __init__(self, mapping: dict[CardKey, int]) -> None:
        self._mapping = mapping
        self._rows: dict[int, dict[str, Any]] = {}
        self._guide_date: datetime | None = None

    @classmethod
    def load(cls) -> CardmarketGuide:
        mapping = load_mappings(cardmarket_dir())
        logger.info("cardmarket_guide: %d cards mapped to Cardmarket products", len(mapping))
        return cls(mapping)

    def apply_guide(self, payload: dict[str, Any]) -> int:
        """Swap in a downloaded price guide, keeping only mapped products."""
        wanted = set(self._mapping.values())
        rows = {
            row["idProduct"]: row
            for row in payload.get("priceGuides") or []
            if row.get("idProduct") in wanted
        }
        self._rows = rows
        self._guide_date = _parse_created_at(payload.get("createdAt"))
        return len(rows)

    def lookup(self, set_code: str, local_id: str, variant: str = "normal") -> EuPrice | None:
        if self._guide_date is None:
            return None
        pid = self._mapping.get((set_code.upper(), pad_local_id(local_id)))
        row = self._rows.get(pid) if pid is not None else None
        if pid is None or row is None:
            return None
        return build_eu_price(pid, row, variant=variant, guide_date=self._guide_date)

    async def refresh(self, client: httpx.AsyncClient) -> None:
        """Download the price guide and apply it. Raises on failure (old data stays)."""
        resp = await client.get(PRICE_GUIDE_URL)
        resp.raise_for_status()
        payload = await asyncio.to_thread(json.loads, resp.content)
        kept = self.apply_guide(payload)
        logger.info(
            "cardmarket_guide: price guide %s applied (%d mapped products)",
            payload.get("createdAt"),
            kept,
        )

    async def run_refresh_loop(
        self, *, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    ) -> None:
        """Refresh forever: every 6 h after success, every 15 min after a failure."""
        if not self._mapping:
            logger.info("cardmarket_guide: no mapping files; EU prices disabled")
            return
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            while True:
                try:
                    await self.refresh(client)
                    delay = REFRESH_INTERVAL_SEC
                except Exception:
                    logger.warning(
                        "cardmarket_guide: refresh failed; keeping previous data", exc_info=True
                    )
                    delay = RETRY_INTERVAL_SEC
                await sleep(delay)
```

- [ ] **Step 5: Run tests**

Run: `uv run python -m pytest tests/unit/test_cardmarket_guide.py -v && uv run python -m pytest`
Expected: 14 new PASS; full suite 433 passed.

- [ ] **Step 6: Commit**

```bash
git add packages/api/watari_api/schemas.py packages/api/watari_api/cardmarket_guide.py tests/unit/test_cardmarket_guide.py
git commit -m "feat(api): add in-memory Cardmarket price guide and EuPrice schema"
```

---

### Task 4: Wire EU prices into the API (`eu_price` on lists, `/eu-price`)

**Files:**
- Modify: `packages/api/watari_api/deps.py`
- Modify: `packages/api/watari_api/main.py` (lifespan)
- Modify: `packages/api/watari_api/schemas.py` (`ArtworkSearchResult`)
- Modify: `packages/api/watari_api/routers/cards.py` (search + by-sets)
- Modify: `packages/api/watari_api/routers/prices.py` (new endpoint)
- Test: `tests/unit/test_api.py`

**Interfaces:**
- Consumes: `CardmarketGuide.load/lookup/run_refresh_loop`, `EuPrice` (Task 3).
- Produces: `deps.get_cardmarket_guide(request) -> CardmarketGuide`; `ArtworkSearchResult.eu_price: EuPrice | None`; `GET /{lang}/cards/{set_code}/{local_id}/eu-price?variant=normal` → `EuPrice` | 404 | 400.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_api.py`:

1. Extend imports:

```python
from watari_api.deps import get_cardmarket_guide, get_catalog, get_price_proxy, get_session
from watari_api.schemas import EuPrice
```

2. Add below the `FakePriceProxy` class:

```python
# ---------------------------------------------------------------------------
# Fake Cardmarket guide
# ---------------------------------------------------------------------------


def _eu_price(price: float = 237.66, basis: str = "normal") -> EuPrice:
    return EuPrice(
        id_product=719658,
        url="https://www.cardmarket.com/en/Pokemon/Products?idProduct=719658&language=7&minCondition=2",
        price_eur=price,
        trend_eur=price,
        avg7_eur=260.84,
        avg30_eur=252.72,
        basis=basis,
        guide_date=datetime(2026, 9, 26, tzinfo=UTC),
    )


class FakeCardmarketGuide:
    """Fake CardmarketGuide — prices keyed by (SET_CODE, local_id, variant)."""

    def __init__(self, prices: dict[tuple[str, str, str], EuPrice] | None = None) -> None:
        self._prices = prices or {}

    def lookup(self, set_code: str, local_id: str, variant: str = "normal") -> EuPrice | None:
        return self._prices.get((set_code.upper(), local_id, variant))
```

3. Update `_make_client` to accept and always install a guide:

```python
def _make_client(
    catalog: FakeMemCatalog | None = None,
    proxy: FakePriceProxy | None = None,
    session: FakeSession | None = None,
    guide: FakeCardmarketGuide | None = None,
) -> TestClient:
    app = create_app()
    if catalog is not None:
        app.dependency_overrides[get_catalog] = lambda: catalog
    if proxy is not None:
        app.dependency_overrides[get_price_proxy] = lambda: proxy
    app.dependency_overrides[get_session] = lambda: (session or FakeSession())
    app.dependency_overrides[get_cardmarket_guide] = lambda: (guide or FakeCardmarketGuide())
    app.dependency_overrides[rate_limit_dep] = _anonymous_ratelimit
    return TestClient(app)
```

4. Add a new section after the international-prices tests:

```python
# ---------------------------------------------------------------------------
# EU (Cardmarket) prices
# ---------------------------------------------------------------------------


def test_eu_price_returns_normal_price() -> None:
    guide = FakeCardmarketGuide({("SV2A", "089", "normal"): _eu_price()})
    client = _make_client(catalog=_catalog_with_card(), guide=guide)
    resp = client.get("/jp/cards/SV2A/089/eu-price")
    assert resp.status_code == 200
    body = resp.json()
    assert body["price_eur"] == 237.66
    assert body["basis"] == "normal"
    assert "low" not in body and "low_eur" not in body
    assert "max-age=1800" in resp.headers["Cache-Control"]


def test_eu_price_mirror_variant() -> None:
    catalog = FakeMemCatalog(
        sets=[_fake_set("SV2A")],
        artworks=[_fake_artwork("SV2A", "089", variants=["normal", "master_ball_mirror"])],
    )
    guide = FakeCardmarketGuide(
        {("SV2A", "089", "master_ball_mirror"): _eu_price(3.85, basis="mirror")}
    )
    client = _make_client(catalog=catalog, guide=guide)
    resp = client.get("/jp/cards/SV2A/089/eu-price?variant=master_ball_mirror")
    assert resp.status_code == 200
    assert resp.json()["basis"] == "mirror"


def test_eu_price_404_when_no_price() -> None:
    client = _make_client(catalog=_catalog_with_card())
    resp = client.get("/jp/cards/SV2A/089/eu-price")
    assert resp.status_code == 404


def test_eu_price_404_for_missing_card() -> None:
    client = _make_client(catalog=FakeMemCatalog(sets=[_fake_set("SV2A")]))
    resp = client.get("/jp/cards/SV2A/999/eu-price")
    assert resp.status_code == 404


def test_eu_price_400_for_unknown_variant() -> None:
    client = _make_client(catalog=_catalog_with_card())
    resp = client.get("/jp/cards/SV2A/089/eu-price?variant=bogus")
    assert resp.status_code == 400


def test_search_results_include_eu_price() -> None:
    guide = FakeCardmarketGuide({("SV2A", "089", "normal"): _eu_price()})
    client = _make_client(catalog=_catalog_with_card(), guide=guide)
    resp = client.get("/jp/cards/search?q=Muk")
    assert resp.status_code == 200
    assert resp.json()[0]["eu_price"]["price_eur"] == 237.66


def test_search_eu_price_null_when_unmapped() -> None:
    client = _make_client(catalog=_catalog_with_card())
    resp = client.get("/jp/cards/search?q=Muk")
    assert resp.json()[0]["eu_price"] is None


def test_by_sets_results_include_eu_price() -> None:
    guide = FakeCardmarketGuide({("SV2A", "089", "normal"): _eu_price()})
    client = _make_client(catalog=_catalog_with_card(), guide=guide)
    get_resp = client.get("/jp/cards/by-sets?codes=SV2A")
    post_resp = client.post("/jp/cards/by-sets", json={"codes": ["SV2A"]})
    assert get_resp.json()[0]["eu_price"]["price_eur"] == 237.66
    assert post_resp.json()[0]["eu_price"]["price_eur"] == 237.66
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/unit/test_api.py -v`
Expected: collection ERROR — `ImportError: cannot import name 'get_cardmarket_guide'`.

- [ ] **Step 3: Implement the dependency and lifespan**

In `deps.py`, add `from watari_api.cardmarket_guide import CardmarketGuide` next to the other `watari_api` imports and, after `get_price_proxy`:

```python
def get_cardmarket_guide(request: Request) -> CardmarketGuide:
    """Return the process-wide Cardmarket price guide from ``app.state``."""
    guide: CardmarketGuide | None = getattr(request.app.state, "cardmarket_guide", None)
    if guide is None:
        raise RuntimeError("cardmarket_guide not installed on app.state; check the FastAPI lifespan")
    return guide
```

In `main.py`: add `import contextlib`; add `from watari_api.cardmarket_guide import CardmarketGuide`; in `lifespan`, right after `await _populate_official_totals(app.state.catalog)`:

```python
    # Cardmarket EU prices: idProduct maps from YAML now; the ~15 MB price
    # guide downloads in the background (lookups return None until it lands).
    app.state.cardmarket_guide = await asyncio.to_thread(CardmarketGuide.load)
    guide_task = asyncio.create_task(app.state.cardmarket_guide.run_refresh_loop())
```

and replace the post-`yield` block with:

```python
    guide_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await guide_task
    if redis is not None:
        await redis.aclose()
```

- [ ] **Step 4: Embed `eu_price` in list results**

In `schemas.py`, add to `ArtworkSearchResult` (after `market_price_source_used`):

```python
    eu_price: EuPrice | None = None  # Cardmarket, normal-print basis
```

In `routers/cards.py`:
- imports: `from watari_api.cardmarket_guide import CardmarketGuide` and `from watari_api.deps import get_cardmarket_guide, get_catalog, get_session`
- aliases: `GuideDep = Annotated[CardmarketGuide, Depends(get_cardmarket_guide)]`
- add below `_enrich_batch_from_db`:

```python
def _attach_eu_prices(results: list[ArtworkSearchResult], guide: CardmarketGuide) -> None:
    """Embed the normal-print Cardmarket price on each result (in-memory, no I/O)."""
    for r in results:
        r.eu_price = guide.lookup(r.set_code, r.local_id, "normal")
```

- add `guide: GuideDep,` after `catalog: CatalogDep,` in `get_cards_by_sets`, `post_cards_by_sets`, and `search_cards`;
- in both by-sets handlers, after `total, results = _cards_by_sets(...)` add `_attach_eu_prices(results, guide)`;
- in `search_cards`, after `await _enrich_search_results_from_db(results, session)` add `_attach_eu_prices(results, guide)`.

- [ ] **Step 5: Add the `/eu-price` endpoint**

In `routers/prices.py`:
- imports: `from watari_api.cardmarket_guide import CardmarketGuide`; `from watari_api.deps import get_cardmarket_guide, get_catalog, get_price_proxy, get_session`; add `EuPrice` to the `watari_api.schemas` import list.
- alias: `GuideDep = Annotated[CardmarketGuide, Depends(get_cardmarket_guide)]`
- module docstring: add the line ``` ``/eu-price``       — Cardmarket price guide (native EUR) from the in-memory CardmarketGuide ```
- add after the `international_prices` handler:

```python
@router.get("/eu-price", response_model=EuPrice)
async def eu_price(
    lang: str,
    set_code: str,
    local_id: str,
    catalog: CatalogDep,
    guide: GuideDep,
    response: Response,
    variant: str = Query("normal"),
) -> EuPrice:
    """Cardmarket price-guide values (native EUR) for one print.

    Mirror variants use Cardmarket's reverse-holo row, which combines Poké Ball
    and Master Ball mirrors. 404 when the card has no Cardmarket mapping/price.
    """
    _resolve_card_id(catalog, lang=lang, set_code=set_code, local_id=local_id, variant=variant)
    price = guide.lookup(set_code, local_id, variant)
    if price is None:
        raise HTTPException(
            status_code=404,
            detail=f"no Cardmarket price for {set_code}/{pad_local_id(local_id)}",
        )
    response.headers["Cache-Control"] = _PRICE_CACHE
    return price
```

- [ ] **Step 6: Run tests**

Run: `uv run python -m pytest tests/unit/test_api.py -v && uv run python -m pytest && make lint`
Expected: 8 new PASS; full suite 441 passed; ruff clean.

- [ ] **Step 7: Commit**

```bash
git add packages/api/watari_api/deps.py packages/api/watari_api/main.py packages/api/watari_api/schemas.py packages/api/watari_api/routers/cards.py packages/api/watari_api/routers/prices.py tests/unit/test_api.py
git commit -m "feat(api): serve Cardmarket EU prices on card lists and /eu-price"
```

---

### Task 5: Remove the per-card TCGdex Cardmarket path

**Files:**
- Modify: `packages/api/watari_api/price_proxy.py`
- Modify: `packages/api/watari_api/routers/prices.py` (`international_prices`)
- Modify: `packages/api/watari_api/schemas.py` (`InternationalPrice` comments)
- Test: `tests/unit/test_api.py`

**Interfaces:**
- Produces: `/international-prices` returns PriceCharting rows only. `PriceProxy` no longer has `fetch_tcgdex_prices` / `tcgdex_international`.

- [ ] **Step 1: Update the tests first**

In `tests/unit/test_api.py` `FakePriceProxy`: delete the `tcgdex_international` method and change `pricecharting_international` to:

```python
    async def pricecharting_international(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self._intl_rows
```

Replace `test_international_prices_returns_rows` with:

```python
def test_international_prices_returns_pricecharting_rows() -> None:
    now = datetime(2025, 4, 1, tzinfo=UTC)
    intl = [
        {
            "card_id": "jp-sv2a-089-normal",
            "market": "pricecharting",
            "condition_label": "Ungraded",
            "price_jpy": 1500,
            "price_raw": 9.5,
            "currency": "USD",
            "observed_at": now,
            "external_url": "https://www.pricecharting.com/game/x/muk-89",
        }
    ]
    client = _make_client(catalog=_catalog_with_card(), proxy=FakePriceProxy(intl_rows=intl))
    resp = client.get("/jp/cards/SV2A/089/international-prices")
    assert resp.status_code == 200
    rows = resp.json()
    assert [r["market"] for r in rows] == ["pricecharting"]
    assert rows[0]["condition_label"] == "Ungraded"
```

- [ ] **Step 2: Run tests to verify the failure**

Run: `uv run python -m pytest tests/unit/test_api.py -k international -v`
Expected: FAIL — `AttributeError: 'FakePriceProxy' object has no attribute 'tcgdex_international'`.

- [ ] **Step 3: Simplify the router**

In `routers/prices.py`, replace the body of `international_prices` (keep signature) with:

```python
    """PriceCharting eBay aggregates for the Japanese card, converted to JPY.

    Cardmarket (EU) prices moved to ``/eu-price``. Returns [] when PriceCharting
    has no match.
    """
    card_id = _resolve_card_id(
        catalog, lang=lang, set_code=set_code, local_id=local_id, variant=variant
    )
    artwork = catalog.get_artwork(set_code, local_id)
    mem_set = catalog.get_set(set_code, language=lang)
    name_en = artwork.name_en if artwork else None
    set_name_en = mem_set.name_en if mem_set else None

    rows = await proxy.pricecharting_international(
        set_code, local_id, name_en, set_name_en, card_id
    )
    response.headers["Cache-Control"] = _PRICE_CACHE
    return [InternationalPrice.model_validate(r) for r in rows]
```

If `asyncio` is no longer used anywhere else in `prices.py` after this change, remove its import (check with `grep -n "asyncio" packages/api/watari_api/routers/prices.py`).

- [ ] **Step 4: Remove the TCGdex code from `price_proxy.py`**

Delete:
- `from watari_catalog.tcgdex_client import TcgdexClient`
- the stale pokemontcg.io comment block (`# Maps JP TCGdex locale set IDs → pokemontcg.io ...` through `# yet implemented; ...`)
- `self._tcgdex_cache` and `self._tcgdex_locks` in `__init__`
- the `# --- TCGdex (TCGPlayer + Cardmarket) ---` section: `fetch_tcgdex_prices` and `tcgdex_international`
- the `# --- TCGdex helpers ---` section: `_parse_tcgdex_date` and `_do_fetch_tcgdex`

Update the `PriceProxy` docstring sources list to:

```python
    Sources:
    - Snkrdunk (JP sold comps + graded)
    - PriceCharting (eBay aggregated raw + PSA graded)

    Cardmarket (EU) prices live in :mod:`watari_api.cardmarket_guide`.
```

Verify nothing references the removed names:
Run: `grep -rn "tcgdex_international\|fetch_tcgdex_prices\|_do_fetch_tcgdex\|_parse_tcgdex_date\|_tcgdex_" packages tests`
Expected: no output.

In `schemas.py` `InternationalPrice`, update the docstring to `"""One western-market price row (PriceCharting eBay aggregates)."""` and the comments to `market: str  # "pricecharting"` and `condition_label: str  # "Ungraded" | "PSA 10" | …`.

- [ ] **Step 5: Run tests + lint**

Run: `uv run python -m pytest && make lint`
Expected: 441 passed; ruff clean (no unused imports).

- [ ] **Step 6: Commit**

```bash
git add packages/api/watari_api/price_proxy.py packages/api/watari_api/routers/prices.py packages/api/watari_api/schemas.py tests/unit/test_api.py
git commit -m "refactor(api): drop per-card TCGdex Cardmarket fetch from international prices"
```

---

### Task 6: Frontend — € currency option and `formatEUR`

**Files:**
- Modify: `apps/web/src/lib/formatters.ts`
- Modify: `apps/web/src/contexts/CurrencyContext.tsx`
- Modify: `apps/web/src/components/layout/CurrencyToggle.tsx`

**Interfaces:**
- Consumes: `GET /rates` → `{USD, EUR}` (Task 1).
- Produces: `Currency = "JPY" | "USD" | "EUR" | "VND"`; `ExchangeRates {USD; EUR; VND}`; `formatEUR(amount: number): string` (e.g. `€1,234.56`).

- [ ] **Step 1: Update formatters**

Replace `formatPrice` in `lib/formatters.ts` and add `formatEUR`:

```ts
const EUR_FORMAT = new Intl.NumberFormat("en-IE", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Native-EUR amounts (Cardmarket). Not currency-converted; bypasses the toggle. */
export function formatEUR(amount: number): string {
  return `€${EUR_FORMAT.format(amount)}`;
}

export function formatPrice(
  jpy: number,
  currency: "JPY" | "USD" | "EUR" | "VND",
  rates: { USD: number; EUR: number; VND: number }
): string {
  if (currency === "USD") {
    return `$${(jpy * rates.USD).toFixed(2)}`;
  }
  if (currency === "EUR") {
    return formatEUR(jpy * rates.EUR);
  }
  if (currency === "VND") {
    return `₫${Math.round(jpy * rates.VND).toLocaleString("vi-VN")}`;
  }
  return formatJPY(jpy);
}
```

- [ ] **Step 2: Update the currency context**

In `contexts/CurrencyContext.tsx`:

```ts
export type Currency = "JPY" | "USD" | "EUR" | "VND";
export interface ExchangeRates {
  USD: number;
  EUR: number;
  VND: number;
}

const FALLBACK_RATES: ExchangeRates = { USD: 0.0065, EUR: 0.0056, VND: 163 };

function useExchangeRates(): ExchangeRates {
  const { data } = useQuery<ExchangeRates>({
    queryKey: ["exchange-rates"],
    // /rates has USD + EUR only (Frankfurter has no VND) — fill gaps from the fallback.
    queryFn: () =>
      apiFetch<Partial<ExchangeRates>>("/rates").then((r) => ({ ...FALLBACK_RATES, ...r })),
    staleTime: 60 * 60 * 1000,
    retry: 1,
  });
  return data ?? FALLBACK_RATES;
}
```

and in `readStoredCurrency`:

```ts
  if (stored === "USD" || stored === "EUR" || stored === "VND") return stored;
```

- [ ] **Step 3: Add the € toggle button**

In `CurrencyToggle.tsx`:

```ts
const OPTIONS: { value: Currency; label: string }[] = [
  { value: "JPY", label: "¥" },
  { value: "USD", label: "$" },
  { value: "EUR", label: "€" },
  { value: "VND", label: "₫" },
];
```

- [ ] **Step 4: Type-check + build**

Run: `cd apps/web && bun run build`
Expected: `tsc -b` passes, vite build succeeds.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/formatters.ts apps/web/src/contexts/CurrencyContext.tsx apps/web/src/components/layout/CurrencyToggle.tsx
git commit -m "feat(web): add EUR to the currency toggle"
```

---

### Task 7: Frontend — EU price block, thumbnail line, EU sort

**Files:**
- Modify: `apps/web/src/types/api.ts`
- Modify: `apps/web/src/api/prices.ts`
- Create: `apps/web/src/components/prices/EuPriceCard.tsx`
- Modify: `apps/web/src/pages/CardDetailPage.tsx`
- Modify: `apps/web/src/components/cards/CardThumbnail.tsx`
- Modify: `apps/web/src/components/cards/SearchCardThumbnail.tsx`
- Modify: `apps/web/src/components/cards/CardFilterBar.tsx`
- Modify: `apps/web/src/pages/CardsSearchPage.tsx`
- Modify: `apps/web/src/lib/sortSearchCards.ts`

**Interfaces:**
- Consumes: `GET /jp/cards/{set}/{id}/eu-price` (Task 4), `eu_price` on search results (Task 4), `formatEUR` (Task 6), `formatDate` (existing).
- Produces: `EuPrice` TS type; `useEuPrice(setCode, localId, variant)`; `SortKey` gains `"eu_price_desc" | "eu_price_asc"`.

- [ ] **Step 1: Types and hook**

In `types/api.ts`, above `ArtworkSearchResult`:

```ts
/** Mirrors packages/api/watari_api/schemas.py: EuPrice (native EUR, Cardmarket price guide) */
export interface EuPrice {
  id_product: number;
  url: string;
  price_eur: number;
  trend_eur: number | null;
  avg7_eur: number | null;
  avg30_eur: number | null;
  basis: "normal" | "mirror";
  guide_date: string;
}
```

and add to `ArtworkSearchResult`: `eu_price: EuPrice | null;`

In `api/prices.ts`, add `EuPrice` to the type import and append:

```ts
export function useEuPrice(setCode: string, localId: string, variant: string) {
  return useQuery<EuPrice | null>({
    queryKey: ["eu-price", setCode, localId, variant],
    queryFn: () =>
      apiFetch<EuPrice>(
        `/jp/cards/${setCode}/${localId}/eu-price?variant=${variant}`
      ).catch((err: Error) => {
        // 404 means no Cardmarket mapping/price for this card — treat as null
        if (err.message.includes("404")) return null;
        throw err;
      }),
    staleTime: 30 * 60 * 1000,
    enabled: setCode.length > 0 && localId.length > 0,
  });
}
```

- [ ] **Step 2: `EuPriceCard` component**

Create `apps/web/src/components/prices/EuPriceCard.tsx`:

```tsx
import { formatDate, formatEUR } from "../../lib/formatters";
import type { EuPrice } from "../../types/api";

const BASIS_LABEL: Record<EuPrice["basis"], string> = {
  normal: "Normal",
  mirror: "Mirror (Poké Ball + Master Ball combined)",
};

function headlineLabel(price: EuPrice): string {
  if (price.trend_eur != null) return "trend";
  if (price.avg30_eur != null) return "30-day avg";
  return "7-day avg";
}

export function EuPriceCard({ price }: { price: EuPrice }) {
  const averages = [
    price.avg7_eur != null ? `7-day avg ${formatEUR(price.avg7_eur)}` : null,
    price.avg30_eur != null ? `30-day avg ${formatEUR(price.avg30_eur)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-bold text-primary-600 dark:text-primary-400 text-glow">
          {formatEUR(price.price_eur)}
        </span>
        <span className="text-xs text-slate-500 dark:text-slate-400">{headlineLabel(price)}</span>
      </div>
      {averages && (
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{averages}</p>
      )}
      <div className="mt-2 flex flex-wrap justify-between gap-2 text-xs text-slate-500 dark:text-slate-400">
        <span>Basis: {BASIS_LABEL[price.basis]}</span>
        <span>Guide: {formatDate(price.guide_date)}</span>
      </div>
      <a
        href={price.url}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-primary-600 hover:underline dark:text-primary-400"
      >
        View JP Near Mint listings on Cardmarket ↗
      </a>
    </div>
  );
}
```

- [ ] **Step 3: Card detail page**

In `pages/CardDetailPage.tsx`:
- add `useEuPrice` to the `../api/prices` import and `import { EuPriceCard } from "../components/prices/EuPriceCard";`
- next to the other price hooks: `const { data: euPrice } = useEuPrice(setCode, localId, variant);`
- insert directly above the `Latest Prices` `<section>`:

```tsx
          {euPrice && (
            <section className="mb-8 glass-panel p-5">
              <h3 className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-200">
                Cardmarket (EU)
              </h3>
              <EuPriceCard price={euPrice} />
            </section>
          )}
```

- [ ] **Step 4: Thumbnail EU line**

In `CardThumbnail.tsx`: import `formatEUR` from `../../lib/formatters`; after the `market` computation add `const euPrice = hasEmbedded ? card.eu_price ?? null : null;`; after the price conditional (`) : null}`) inside the name/price `<div>` add:

```tsx
        {euPrice && (
          <p className="text-[11px] text-slate-500 dark:text-slate-400">
            EU {formatEUR(euPrice.price_eur)}
          </p>
        )}
```

In `SearchCardThumbnail.tsx`: import `formatEUR`; after the price `<p>` (the one rendering `formatPrice(displayPrice)`) add:

```tsx
        {card.eu_price && (
          <p className="text-[11px] text-slate-500 dark:text-slate-400">
            EU {formatEUR(card.eu_price.price_eur)}
          </p>
        )}
```

- [ ] **Step 5: EU sort**

In `CardFilterBar.tsx`, extend the type:

```ts
export type SortKey =
  | "number"
  | "name_asc"
  | "name_desc"
  | "rarity_desc"
  | "rarity_asc"
  | "price_desc"
  | "price_asc"
  | "eu_price_desc"
  | "eu_price_asc";
```

and after `<option value="price_asc">Market price (asc)</option>` add (in **both** `CardFilterBar.tsx` and `pages/CardsSearchPage.tsx`):

```tsx
              <option value="eu_price_desc">EU price (desc)</option>
              <option value="eu_price_asc">EU price (asc)</option>
```

In `lib/sortSearchCards.ts`, add below `displayPrice`:

```ts
function euPrice(c: ArtworkSearchResult): number | null {
  return c.eu_price?.price_eur ?? null;
}
```

and two cases in the switch (cards without an EU price sort last both ways):

```ts
      case "eu_price_desc":
        return (euPrice(b) ?? -1) - (euPrice(a) ?? -1);
      case "eu_price_asc":
        return (euPrice(a) ?? Infinity) - (euPrice(b) ?? Infinity);
```

- [ ] **Step 6: Type-check + build**

Run: `cd apps/web && bun run build`
Expected: passes (the `SortKey` switch stays exhaustive; no `any`).

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/types/api.ts apps/web/src/api/prices.ts apps/web/src/components/prices/EuPriceCard.tsx apps/web/src/pages/CardDetailPage.tsx apps/web/src/components/cards/CardThumbnail.tsx apps/web/src/components/cards/SearchCardThumbnail.tsx apps/web/src/components/cards/CardFilterBar.tsx apps/web/src/pages/CardsSearchPage.tsx apps/web/src/lib/sortSearchCards.ts
git commit -m "feat(web): show Cardmarket EU price on detail, thumbnails, and sort"
```

---

### Task 8: Backfill mapping files + live smoke test

**Files:**
- Create (generated): `packages/catalog/data/cardmarket/*.yml`

- [ ] **Step 1: Run the full backfill**

Run (long: ~12k TCGdex calls, expect 10–40 min; run in background): `make catalog-cardmarket-map`
Expected: one `cardmarket-map: <SET> — N/M mapped` log line per set; sets not on TCGdex (CLF/CLL/CLK/SMPR/SP and un-bootstrapped promos) log "no file written" or "no card YAMLs".

- [ ] **Step 2: Sanity-check coverage**

Run:
```bash
ls packages/catalog/data/cardmarket | wc -l
grep -h "^  mapped\|^  artworks" packages/catalog/data/cardmarket/SV2A.yml
grep "'205'" packages/catalog/data/cardmarket/SV2A.yml
uv run python - <<'EOF'
import glob, yaml
low = []
for p in sorted(glob.glob("packages/catalog/data/cardmarket/*.yml")):
    d = yaml.safe_load(open(p))
    t = d["totals"]
    if t["mapped"] < 0.8 * t["artworks"]:
        low.append((d["set_code"], t["mapped"], t["artworks"]))
print("sets under 80% mapped:", low)
EOF
```
Expected: SV2A `artworks: 210`, `mapped: 210`, `'205': 719658`. Report any sets under 80% to the user (likely brand-new sets not yet on Cardmarket).

- [ ] **Step 3: Live smoke of the guide (real download, no DB)**

Run:
```bash
uv run python - <<'EOF'
import asyncio, httpx
from watari_api.cardmarket_guide import CardmarketGuide

async def main():
    g = CardmarketGuide.load()
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as c:
        await g.refresh(c)
    for args in [("SV2A", "205"), ("SV2A", "089"), ("SV2A", "089", "master_ball_mirror"), ("M2A", "001")]:
        print(args, g.lookup(*args))

asyncio.run(main())
EOF
```
Expected: SV2A/205 `price_eur` ≈ 237 (trend), `basis='normal'`; SV2A/089 mirror uses holo values; M2A/001 non-None.

- [ ] **Step 4: Commit the data**

```bash
git add packages/catalog/data/cardmarket
git commit -m "chore(catalog): add Cardmarket idProduct maps for all TCGdex-indexed sets"
```

---

### Task 9: Docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-09-26-cardmarket-eu-price-design.md` (close open item, note amendments)
- Modify: memory `/Users/minhpham/.claude/projects/-Users-minhpham-Desktop-watari/memory/` (not in repo)

- [ ] **Step 1: Update `CLAUDE.md`**

- Header "Last updated" line: `2026-09-26 (**Cardmarket EU price** — native-EUR eu_price on search/by-sets + /eu-price; generated data/cardmarket/*.yml idProduct maps; price guide held in API memory; € in currency toggle; Frankfurter host fix)`.
- §2 repo layout, under `packages/catalog/data/`: `cardmarket/{SET}.yml ← generated local_id → Cardmarket idProduct maps`.
- §3.5 route table: add row `` `GET /{lang}/cards/{set_code}/{local_id}/eu-price` (`?variant=normal`) | `EuPrice` / 404 | `CardmarketGuide` (in-memory price guide, refreshed every 6 h) ``; change the `/international-prices` row to "PriceCharting (eBay) only"; add a note that `/cards/search` and `/cards/by-sets` results carry `eu_price`.
- §3.7: currency toggle is ¥·$·€·₫; `/rates` returns USD+EUR (VND always from the frontend fallback); add `useEuPrice` to the hooks table; mention `EuPriceCard` on `CardDetailPage` and the `EU €x` thumbnail line; add "EU price (desc/asc)" sort.
- §6: replace invariant **39** with:
  > **39. Cardmarket EU prices come from `data/cardmarket/<SET>.yml` + the in-memory price guide.** Map files are generated by `make catalog-cardmarket-map [SET=...]` (TCGdex JP `pricing.cardmarket.idProduct`); never hand-edit, never match by name (Cardmarket names aren't unique per expansion). `CardmarketGuide` downloads `price_guide_6.json` every 6 h (15-min retry, last good data kept). The price guide has no condition/language breakdown: `low` is deliberately not exposed, and Poké Ball/Master Ball mirrors share the `*-holo` row (`basis="mirror"`). Sets without a YAML `tcgdex_id` resolve via `resolve_tcgdex_id` (set_code, or `SVP→SV-P`, `MP→M-P`). Run the map command after bootstrapping any new set.
- Invariant **24**: append "Exception: native-EUR `EuPrice` fields render with `formatEUR` (they are Cardmarket's own numbers, not converted JPY)."
- Add invariant **41**: "**Frankfurter lives at `https://api.frankfurter.dev/v1/latest`** (`FRANKFURTER_LATEST_URL`). The old `.app` host 301s and httpx doesn't follow redirects by default — keep `follow_redirects=True`. Frankfurter has no VND."
- §7 commands: `make catalog-cardmarket-map [SET=SV2A] [REFRESH=1]  # Cardmarket idProduct maps (TCGdex JP)`.
- Test count in §1/§4.1: update to the final `uv run python -m pytest` total.

- [ ] **Step 2: Close the spec's open item**

In the spec §3.6, replace the "Open item" paragraph with: "Verified 2026-09-26 in a browser: `https://www.cardmarket.com/en/Pokemon/Products?idProduct={id}` resolves to the product page." Add a short "Amendments" list at the end mirroring this plan's "Spec amendments" section.

- [ ] **Step 3: Update memory**

Update `MEMORY.md` state snapshot line and add a one-line pointer to a new memory file `cardmarket-eu-price.md` (type: project) summarizing: shipped date, data flow (map files → in-memory guide), `low` excluded + mirror basis, Frankfurter host move, NM floor deferred (sources: product-page scrape blocked by Cloudflare JS challenge; official API closed; paid scrapers).

- [ ] **Step 4: Final verification + commit**

Run: `uv run python -m pytest && make lint && (cd apps/web && bun run build)`
Expected: all green.

```bash
git add CLAUDE.md docs/superpowers/specs/2026-09-26-cardmarket-eu-price-design.md
git commit -m "docs: document Cardmarket EU price pipeline and invariants"
```
