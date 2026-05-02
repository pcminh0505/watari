#!/usr/bin/env python3
"""Generate packages/catalog/data/sets/S*.yml for Japanese Sword & Shield era.

Includes main expansions, enhanced packs, and high-class packs (Shiny Star V,
VMAX Climax, VSTAR Universe).

TCGdex IDs follow the official JP API (e.g. S8b, S12a). **S11** is *Lost Abyss*
on Pokellector; TCGdex `S11` is a different set, so we omit `tcgdex_id` for
Lost Abyss and use manual metadata.

Run: uv run python scripts/gen_sw_set_metadata.py
"""

from __future__ import annotations

import json
import pathlib
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
SETS_DIR = ROOT / "packages" / "catalog" / "data" / "sets"

# (set_code, tcgdex_id or None, pokellector_slug)
SPECS: list[tuple[str, str | None, str]] = [
    ("S1W", "S1W", "Sword-Expansion"),
    ("S1H", "S1H", "Shield-Expansion"),
    ("S2", "S2", "Rebellion-Crash-Expansion"),
    ("S3", "S3", "Infinity-Zone-Expansion"),
    ("S4", "S4", "Electrifying-Tackle-Expansion"),
    ("S5I", "S5I", "Single-Strike-Master-Expansion"),
    ("S5R", "S5R", "Rapid-Strike-Master-Expansion"),
    ("S6H", "S6H", "Silver-Lance-Expansion"),
    ("S6K", "S6K", "Jet-Black-Spirit-Expansion"),
    ("S7D", "S7D", "Towering-Perfection-Expansion"),
    ("S7R", "S7R", "Blue-Sky-Stream-Expansion"),
    ("S8", "S8", "Fusion-ARTS-Expansion"),
    ("S9", "S9", "Star-Birth-Expansion"),
    ("S10D", "S10D", "Time-Gazer-Expansion"),
    ("S10P", "S10P", "Space-Juggler-Expansion"),
    # Pokellector duplicates HTML name="S12" for Lost Abyss vs Paradigm; we use S11/S12.
    ("S11", None, "Lost-Abyss-Expansion"),
    ("S12", "S12", "Paradigm-Trigger-Expansion"),
    ("S1A", "S1a", "VMAX-Rising-Expansion"),
    ("S2A", "S2a", "Explosive-Flame-Walker-Expansion"),
    ("S3A", "S3a", "Legendary-Pulse-Expansion"),
    ("S4A", "S4a", "Shiny-Star-V-Expansion"),
    ("S5A", "S5a", "Matchless-Fighter-Expansion"),
    ("S6A", "S6a", "Eevee-Heroes-Expansion"),
    ("S8A", "S8a", "25th-Anniversary-Collection-Expansion"),
    ("S8B", "S8b", "VMAX-Climax-Expansion"),
    ("S9A", "S9a", "Battle-Region-Expansion"),
    ("S10A", "S10a", "Dark-Phantasma-Expansion"),
    ("S10B", "S10b", "Japanese-Pokemon-GO-Expansion"),
    ("S11A", "S11a", "Incandescent-Arcana-Expansion"),
    ("S12A", "S12a", "VSTAR-Universe-Expansion"),
]

MANUAL: dict[str, tuple[str, str, str]] = {
    # TCGdex JP uses id S11 for another product; Lost Abyss has no dedicated entry.
    "S11": ("2022-07-15", "ロストアビス", "Lost Abyss"),
}

# TCGdex /en often lacks Sword-era ids — prefer canonical English names here.
NAME_EN_OVERRIDE: dict[str, str] = {
    "S4A": "Shiny Star V",
    "S8B": "VMAX Climax",
    "S12A": "VSTAR Universe",
    "S12": "Paradigm Trigger",
}


def _fetch_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "watari-catalog-gen/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _tcgdex_urls(tcgdex_id: str) -> tuple[str, str]:
    from urllib.parse import quote

    enc = quote(tcgdex_id, safe="")
    return (
        f"https://api.tcgdex.net/v2/ja/sets/{enc}",
        f"https://api.tcgdex.net/v2/en/sets/{enc}",
    )


def main() -> None:
    SETS_DIR.mkdir(parents=True, exist_ok=True)
    for set_code, tcgdex_id, pokellector_slug in SPECS:
        path = SETS_DIR / f"{set_code}.yml"
        if tcgdex_id:
            ja_url, en_url = _tcgdex_urls(tcgdex_id)
            ja = _fetch_json(ja_url)
            en = _fetch_json(en_url)
            if ja is None:
                raise RuntimeError(f"TCGdex missing {tcgdex_id} for {set_code}")
            name_ja = ja.get("name") or ""
            name_en = (en or {}).get("name") or name_ja
            release_date = ja.get("releaseDate") or ""
        else:
            release_date, name_ja, name_en = MANUAL[set_code]

        if set_code in NAME_EN_OVERRIDE:
            name_en = NAME_EN_OVERRIDE[set_code]

        lines = [
            "# Japanese Pokémon TCG set entry. Edit with care: used by seed-sets.",
            "",
            f"set_code: {set_code}",
            "era_block: sw",
            "language: jp",
            f"name_ja: {name_ja}",
            f"name_en: {name_en}",
            f"release_date: {release_date}",
        ]
        if tcgdex_id:
            lines.append(f"tcgdex_id: {tcgdex_id}")
        lines.append(f"pokellector_slug: {pokellector_slug}")
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        print("wrote", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
