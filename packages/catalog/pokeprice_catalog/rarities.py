"""Canonical rarity codes + translation maps from TCGdex / Cardrush.

Canonical codes (upper-case, short, stable):

    C    - Common
    U    - Uncommon
    R    - Rare
    RR   - Double Rare (ex / two-star)
    AR   - Art Rare
    SR   - Super Rare (full-art trainer, non-ex pokémon full art legacy)
    SAR  - Special Art Rare
    UR   - Ultra Rare (gold / rainbow / trophy)
    CSR  - Character Super Rare (legacy, classic-era)
    HR   - Hyper Rare (legacy)
    RRR  - Triple Rare (legacy Sword & Shield)
    MA   - Masterball Mirror (ME-era parallel)
    MUR  - Masterball Ultra Rare (proposed ME-era)

Anything not covered is tagged ``UNK`` and logged so we can extend the map.
"""

from __future__ import annotations

CANONICAL_RARITIES: set[str] = {
    "C",
    "U",
    "R",
    "RR",
    "AR",
    "SR",
    "SAR",
    "UR",
    "CSR",
    "HR",
    "RRR",
    "MA",
    "MUR",
}


TCGDEX_RARITY_MAP: dict[str, str] = {
    # --- TCGdex `rarity` values seen for Japanese sets (as of 2026-04) ---
    "Common": "C",
    "Uncommon": "U",
    "Rare": "R",
    "Double rare": "RR",
    "Ultra Rare": "UR",
    "Illustration rare": "AR",
    "Special illustration rare": "SAR",
    "Hyper rare": "HR",
    "Shiny rare": "SR",           # S-series legacy (approximate)
    "Shiny Double rare": "SSR",   # keep raw; mapped to SSR below
    "ACE SPEC Rare": "R",         # no distinct slot in v1
    "Amazing Rare": "RRR",
    "Radiant Rare": "K",          # keep raw
    "Character Rare": "CHR",
    "Character Super Rare": "CSR",
    "Trainer Gallery Rare Holo": "TR",
}


CARDRUSH_RARITY_MAP: dict[str, str] = {
    # Cardrush encodes rarity as the trailing tag in product names
    # (e.g. ``ポケモンカード sv2a 163/165 ミュウツー ex SAR``).
    "C": "C",
    "U": "U",
    "R": "R",
    "RR": "RR",
    "AR": "AR",
    "SR": "SR",
    "SAR": "SAR",
    "UR": "UR",
    "HR": "HR",
    "RRR": "RRR",
    "MA": "MA",
    "MUR": "MUR",
    "CSR": "CSR",
    "CHR": "CHR",
    "S": "SR",   # legacy shortcut
    "K": "K",    # radiant (S-era) — keep raw
    "TR": "TR",
    "ACE": "R",  # ACE SPEC
}


def canonicalize_tcgdex(raw: str | None) -> str | None:
    """Map a TCGdex rarity string to a canonical code; ``None`` if unmappable."""
    if not raw:
        return None
    mapped = TCGDEX_RARITY_MAP.get(raw.strip())
    if mapped is None:
        return None
    return mapped


def canonicalize_cardrush(raw: str | None) -> str | None:
    """Map a Cardrush rarity tag to a canonical code; ``None`` if unmappable."""
    if not raw:
        return None
    mapped = CARDRUSH_RARITY_MAP.get(raw.strip().upper())
    if mapped is None:
        return None
    return mapped


POKELLECTOR_RARITY_MAP: dict[str, str] = {
    # --- English-side TCG labels (some SV-era sets use these) ---
    "Common": "C",
    "Uncommon": "U",
    "Rare": "R",
    "Rare Holo": "R",
    "Double Rare": "RR",
    "Ultra Rare": "UR",
    "Illustration Rare": "AR",
    "Special Illustration Rare": "SAR",
    "Hyper Rare": "HR",
    "Shiny Rare": "SR",
    "Shiny Ultra Rare": "SSR",
    "ACE SPEC Rare": "R",
    "Amazing Rare": "RRR",
    "Radiant Rare": "K",
    "Character Rare": "CHR",
    "Character Super Rare": "CSR",
    "Trainer Gallery Rare Holo": "TR",
    # --- Japanese-side labels used on `jp.pokellector.com` ---
    # Japanese sets collapse some English distinctions (no "Uncommon"; Art
    # Rare ≠ Illustration Rare, etc.).
    "Art Rare": "AR",
    "Super Rare": "SR",
    "Special Art Rare": "SAR",
    # Mega Evolution era additions (Masterball Mirror parallel)
    "Master Ball Rare": "MA",
    "Masterball Rare": "MA",
}


def canonicalize_pokellector(raw: str | None) -> str | None:
    """Map a Pokellector rarity label to a canonical code; ``None`` if unmappable."""
    if not raw:
        return None
    mapped = POKELLECTOR_RARITY_MAP.get(raw.strip())
    if mapped is None:
        return None
    return mapped
