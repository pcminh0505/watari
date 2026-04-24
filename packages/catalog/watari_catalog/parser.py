"""Parse Cardrush product-name strings for catalog extraction.

Cardrush product names embed several signals in free-form text:

- set code  (e.g. ``sv2a``, ``m2a``)
- local id / total  (e.g. ``163/165``, ``001/102``)
- rarity tag  (``SAR``, ``【AR】``, trailing token)
- variant hint  (``マスターボール柄``, ``リバース``, ``ジャンボ``)
- Japanese card name

The parser is deliberately lenient — each signal is best-effort and ``None``
on miss. Consumers should defensively drop rows where essential fields
(``local_id``) are missing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from watari_catalog.rarities import CARDRUSH_RARITY_MAP, canonicalize_cardrush
from watari_catalog.variants import (
    DEFAULT_VARIANT,
    detect_variant_from_cardrush_name,
)

# -- Regex building blocks ------------------------------------------------

_SET_LOCAL_RE = re.compile(
    r"""
    (?P<set>[A-Za-z]{1,5}\d[A-Za-z]?)   # set code (sv2a, s12a, m2a, pmcl, ...)
    \s+
    (?P<local>\d{1,4})                  # local id
    (?:/(?P<total>\d{1,4}))?            # optional total
    """,
    re.VERBOSE,
)

# Fallback: bracketed code like {163/165} or (163/165)
_BRACKET_CODE_RE = re.compile(r"[{(](?P<local>\d{1,4})/(?P<total>\d{1,4})[})]")

# Bracketed rarity like 【SAR】, 【AR】, 【UR】 (Cardrush common on crawl listings).
_BRACKET_RARITY_RE = re.compile(r"【([A-Z]{1,4})】")

# Trailing bare rarity token at end of string (``... SAR`` / ``... MA``).
_TRAILING_RARITY_RE = re.compile(
    r"\s+(" + "|".join(sorted(CARDRUSH_RARITY_MAP.keys(), key=len, reverse=True)) + r")\s*$"
)

# Tokens to strip when recovering card_name_ja (price, condition, rarity tags).
_NAME_NOISE_RE = re.compile(
    r"""
    ポケモンカード
  | ポケカ
  | [〔【][^〕】]*[〕】]          # any bracketed tag (condition, rarity, ...)
  | [{(]\d{1,4}/\d{1,4}[})]       # bracketed codes
  | \d{1,4}/\d{1,4}               # bare local/total
  | ￥[\d,]+|¥[\d,]+|[\d,]+円
  | \b(?:PSA|BGS|CGC|SGC)\d+\b
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class ParsedCardrushName:
    """Outcome of parsing a Cardrush product-name string."""

    set_code: str | None
    local_id: str | None
    total: int | None
    rarity_code: str | None
    variant: str
    name_ja: str | None


def parse_cardrush_product_name(name: str) -> ParsedCardrushName:
    """Parse a Cardrush product title into catalog fields."""
    if not name:
        return ParsedCardrushName(None, None, None, None, DEFAULT_VARIANT, None)

    # 1) set + local (preferred: `sv2a 163/165`)
    set_code: str | None = None
    local_id: str | None = None
    total: int | None = None
    if m := _SET_LOCAL_RE.search(name):
        set_code = m.group("set").lower()
        local_id = m.group("local")
        if t := m.group("total"):
            total = int(t)
    elif m := _BRACKET_CODE_RE.search(name):
        local_id = m.group("local")
        total = int(m.group("total"))

    # 2) rarity (prefer bracketed, else trailing bare token)
    rarity_code: str | None = None
    if (m := _BRACKET_RARITY_RE.search(name)) or (m := _TRAILING_RARITY_RE.search(name)):
        rarity_code = canonicalize_cardrush(m.group(1))

    # 3) variant
    variant = detect_variant_from_cardrush_name(name)

    # 4) card name (best effort: remove known noise + all-latin set/local blob)
    cleaned = _NAME_NOISE_RE.sub(" ", name)
    if set_code:
        cleaned = re.sub(rf"\b{re.escape(set_code)}\b", " ", cleaned, flags=re.IGNORECASE)
    # also remove any standalone trailing rarity
    cleaned = _TRAILING_RARITY_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" 　・-_")
    name_ja = cleaned or None

    return ParsedCardrushName(
        set_code=set_code,
        local_id=local_id,
        total=total,
        rarity_code=rarity_code,
        variant=variant,
        name_ja=name_ja,
    )
