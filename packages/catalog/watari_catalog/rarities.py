"""Canonical rarity codes + translation maps from TCGdex / Cardrush.

Canonical codes (upper-case, short, stable):

    C    - Common
    U    - Uncommon
    R    - Rare
    RR   - Double Rare (ex / two-star)
    AR   - Art Rare
    S    - Shiny (baby shiny / shiny basic tier — SV4A, S4A)
    SR   - Super Rare (full-art trainer, non-ex pokémon full art legacy)
    SSR  - Shiny Super Rare (shiny V/VMAX full-art — S4A, S8B)
    SAR  - Special Art Rare
    UR   - Ultra Rare (gold / rainbow / trophy)
    CSR  - Character Super Rare (legacy, SWSH-era)
    CHR  - Character Rare (legacy, SWSH-era)
    HR   - Hyper Rare (SM-era gold full-art)
    TR   - Trainer Gallery Rare Holo (SWSH Trainer Gallery)
    K    - Radiant Rare (SWSH era)
    RRR  - Triple Rare / Amazing Rare (legacy Sword & Shield)
    MA   - Masterball Mirror (ME-era parallel)
    MUR  - Masterball Ultra Rare (proposed ME-era)

Anything not covered is tagged ``UNK`` and logged so we can extend the map.
"""

from __future__ import annotations

import re as _re

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
    "Shiny rare": "S",            # baby shiny tier (SV4A, S4A)
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
    "S": "S",    # shiny tier (baby shinies in SV4A, S4A)
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
    "Shiny Rare": "S",
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
    # SM-era additions
    "Secret Rare": "UR",    # SM/SW gold/rainbow + secret alt-arts
    "Prism Star": "SR",     # SM-era ◇ prism cards (similar tier to Super Rare)
    # SWSH-era additions
    "Shiny": "S",           # baby shiny tier (SV4A Shiny Treasure, S4A Shiny Star V)
    # SV-era labels (jp.pokellector.com uses shorter forms than EN Pokellector)
    "Ace Spec": "R",                # ACE SPEC cards (same tier as ACE SPEC Rare)
    "Super Secret Rare": "SSR",     # shiny ex/V/VMAX (SV4A, S4A — Shiny Super Rare tier)
    "B Double Rare": "RR",          # SV11 box-topper ex (Double Rare tier)
}


def canonicalize_pokellector(raw: str | None) -> str | None:
    """Map a Pokellector rarity label to a canonical code; ``None`` if unmappable."""
    if not raw:
        return None
    mapped = POKELLECTOR_RARITY_MAP.get(raw.strip())
    if mapped is None:
        return None
    return mapped


# ---------------------------------------------------------------------------
# TCGCollector
# ---------------------------------------------------------------------------
#
# TCGCollector exposes two flavours of rarity strings:
#
#   1. English label with a parenthesised canonical code, used on the
#      English-side per-card detail page (every JP card is duplicated to
#      this namespace). Examples: ``"Common (C)"``, ``"Special Art Rare
#      (SAR)"``, ``"Hyper Rare (HR)"``. The code in the parens already
#      matches our canonical alphabet, so we extract it directly.
#
#   2. Native Japanese label, occasionally seen on the Japanese-locale
#      experimental page. Examples: ``"コモン"``, ``"アートレア"``. The
#      JA labels are deterministic and live below.
#
# Both are funneled through ``canonicalize_tcgcollector(raw)``.

_TCGCOLLECTOR_PARENS_RE = _re.compile(r"\(([A-Z]+)\)\s*$")


TCGCOLLECTOR_JA_RARITY_MAP: dict[str, str] = {
    # Standard tiers
    "コモン": "C",
    "アンコモン": "U",
    "レア": "R",
    "ダブルレア": "RR",
    "ウルトラレア": "UR",
    "アートレア": "AR",
    "スペシャルアートレア": "SAR",
    "ハイパーレア": "HR",
    "シャイニーレア": "S",
    "シャイニースーパーレア": "SSR",
    # SwSh-era
    "アメイジングレア": "RRR",
    "キャラクターレア": "CHR",
    "キャラクタースーパーレア": "CSR",
    "TR (トレーナーズレア)": "TR",
    "ラディアントレア": "K",
    # ME-era
    "マスターボールレア": "MA",
    "マスターウルトラレア": "MUR",
}


# Map of TCGCollector's English-only rarity labels (when the parenthesised
# code is missing or non-canonical, fall back to the literal label).
TCGCOLLECTOR_EN_RARITY_MAP: dict[str, str] = {
    "Common": "C",
    "Uncommon": "U",
    "Rare": "R",
    "Double Rare": "RR",
    "Art Rare": "AR",
    "Super Rare": "SR",
    "Special Art Rare": "SAR",
    "Ultra Rare": "UR",
    "Hyper Rare": "HR",
    "Shiny Rare": "S",
    "Shiny Ultra Rare": "SSR",
    "Shiny Super Rare": "SSR",
    "Amazing Rare": "RRR",
    "Radiant Rare": "K",
    "Character Rare": "CHR",
    "Character Super Rare": "CSR",
    "Trainer Gallery Rare Holo": "TR",
    "ACE SPEC Rare": "R",
    "Master Ball Rare": "MA",
    "Masterball Rare": "MA",
    "Prism Star": "SR",
    "Black Star Promo": "PR",
}


def canonicalize_tcgcollector(raw: str | None) -> str | None:
    """Map a TCGCollector rarity label to a canonical code.

    Tries (in order):

    1. Trailing parenthesised code, e.g. ``"Special Art Rare (SAR)"`` →
       ``"SAR"``. This is the most reliable because TCGCollector emits
       the canonical code itself.
    2. English-only label, e.g. ``"Special Art Rare"`` → ``"SAR"``.
    3. Native JP label, e.g. ``"スペシャルアートレア"`` → ``"SAR"``.

    Returns ``None`` on anything we don't recognize so the caller can
    surface it for a manual rarity-map extension.
    """
    if not raw:
        return None
    s = raw.strip()
    m = _TCGCOLLECTOR_PARENS_RE.search(s)
    if m:
        code = m.group(1).upper()
        # Sanity: codes we accept are at most 4 letters + appear in our
        # canonical alphabet. Anything else falls through to label match.
        if 1 <= len(code) <= 4 and code.isalpha():
            return code
    label = s
    # Strip trailing parens if any
    if "(" in label:
        label = label.rsplit("(", 1)[0].strip()
    if label in TCGCOLLECTOR_EN_RARITY_MAP:
        return TCGCOLLECTOR_EN_RARITY_MAP[label]
    if label in TCGCOLLECTOR_JA_RARITY_MAP:
        return TCGCOLLECTOR_JA_RARITY_MAP[label]
    return None
