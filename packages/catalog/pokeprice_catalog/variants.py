"""Canonical variant slugs + detection from Cardrush product names.

Known variants (slug registry):

    normal               - default print
    reverse_holo         - reverse-holo variant
    master_ball_mirror   - Masterball-pattern mirror (``マスターボール柄``)
    poke_ball_mirror     - Pokéball-pattern mirror (``モンスターボール柄``)
    quick_ball_mirror    - Quickball-pattern mirror (``クイックボール柄``)
    ultra_ball_mirror    - Ultraball-pattern mirror (``ハイパーボール柄``)
    promo                - promo stamp / holo-stamped print
    jumbo                - jumbo-size card
"""

from __future__ import annotations

import re

DEFAULT_VARIANT = "normal"

CANONICAL_VARIANTS: set[str] = {
    "normal",
    "reverse_holo",
    "master_ball_mirror",
    "poke_ball_mirror",
    "quick_ball_mirror",
    "ultra_ball_mirror",
    "promo",
    "jumbo",
}


# Ordered so a product name with several markers picks the most specific first.
_CARDRUSH_VARIANT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("master_ball_mirror", re.compile(r"マスターボール(?:柄|ミラー)")),
    ("poke_ball_mirror", re.compile(r"モンスターボール(?:柄|ミラー)")),
    ("quick_ball_mirror", re.compile(r"クイックボール(?:柄|ミラー)")),
    ("ultra_ball_mirror", re.compile(r"ハイパーボール(?:柄|ミラー)")),
    ("reverse_holo", re.compile(r"リバース|ミラー仕様|キラ仕様")),
    ("jumbo", re.compile(r"ジャンボ")),
    ("promo", re.compile(r"プロモ")),
]


def detect_variant_from_cardrush_name(name: str) -> str:
    """Best-effort variant detection from a Cardrush product name.

    Returns ``'normal'`` when nothing matches.
    """
    for slug, pattern in _CARDRUSH_VARIANT_PATTERNS:
        if pattern.search(name):
            return slug
    return DEFAULT_VARIANT
