#!/usr/bin/env python3
"""Generate packages/catalog/data/sets/SM*.yml from TCGdex + Pokellector slugs.

Run from repo root: uv run python scripts/gen_sm_set_metadata.py
"""

from __future__ import annotations

import json
import pathlib
import urllib.request
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parents[1]
SETS_DIR = ROOT / "packages" / "catalog" / "data" / "sets"

# (filename stem == set_code, tcgdex id or None, pokellector_slug)
SPECS: list[tuple[str, str | None, str]] = [
    ("SM0", "SM0", "Pikachu-New-Friends-Expansion"),
    ("SM1S", "SM1S", "Collection-Sun-Expansion"),
    ("SM1M", "SM1M", "Collection-Moon-Expansion"),
    ("SM1P", "SM1+", "Sun-Moon-Strengthening-Expansion-Expansion"),
    ("SM2P", "sm2+", "Strengthening-Expansion-Pack-Beyond-A-New-Challeng-Expansion"),
    ("SM2K", "SM2K", "Islands-Awaiting-You-Expansion"),
    ("SM2L", "SM2L", "Alola-Moonlight-Expansion"),
    ("SM3H", "SM3H", "Seen-the-Rainbow-Battle-Expansion"),
    ("SM3N", "SM3N", "Light-Consuming-Darkness-Expansion"),
    ("SM3P", "SM3+", "Strengthening-Expansion-Shining-Legends-Expansion"),
    ("SM4S", "SM4S", "The-Awoken-Hero-Expansion"),
    ("SM4A", "SM4A", "The-Transdimensional-Beast-Expansion"),
    ("SM4P", "SM4+", "GX-Battle-Boost-Expansion"),
    ("SM5S", "SM5S", "Ultra-Sun-Expansion"),
    ("SM5M", "SM5M", "Ultra-Moon-Expansion"),
    ("SM5P", "SM5+", "Ultra-Force-Expansion"),
    ("SM6", "SM6", "Japanese-Forbidden-Light-Expansion"),
    ("SM6A", "SM6a", "Dragon-Storm-Expansion"),
    ("SM6B", "SM6b", "Champion-Road-Expansion"),
    ("SM7", "SM7", "Charisma-of-the-Cracked-Sky-Expansion"),
    ("SM7A", "SM7a", "Thunderclap-Spark-Expansion"),
    ("SM7B", "SM7b", "Fairy-Rise-Expansion"),
    ("SM8", "SM8", "Explosive-Impact-Expansion"),
    ("SM8A", "SM8a", "Dark-Order-Expansion"),
    ("SM8B", "SM8b", "Ultra-Shiny-GX-Expansion"),
    ("SM9", "SM9", "Tag-Bolt-Expansion"),
    ("SM9A", "SM9a", "Night-Unison-Expansion"),
    ("SM9B", "SM9b", "Full-Metal-Wall-Expansion"),
    ("SM10", "SM10", "Double-Blaze-Expansion"),
    ("SM10A", None, "GG-End-Expansion"),
    ("SM10B", "SM10b", "Sky-Legend-Expansion"),
    ("SM11", None, "Miracle-Twins-Expansion"),
    ("SM11A", "SM11a", "Remix-Bout-Expansion"),
    ("SM11B", "SM11b", "Dream-League-Expansion"),
    ("SM12", "SM12", "Alter-Genesis-Expansion"),
    ("SM12A", "SM12a", "Tag-Team-GX-All-Stars-Expansion"),
    ("SMP2", "SMP2", "Japanese-Detective-Pikachu-Expansion"),
]

# Manual rows when TCGdex has no set (release_date ISO, ja, en)
MANUAL: dict[str, tuple[str, str, str]] = {
    "SM10A": ("2019-04-05", "ジージーエンド", "GG End"),
    # TCGdex JP API omits SM11 (miracle twin); names/dates per Bulbapedia main-set list.
    "SM11": ("2019-05-31", "ミラクルツイン", "Miracle Twin"),
}


def _fetch_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "watari-catalog-gen/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _tcgdex_urls(tcgdex_id: str) -> tuple[str, str]:
    """Quote set ids that contain + or other reserved characters."""
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

        lines = [
            "# Japanese Pokémon TCG set entry. Edit with care: used by seed-sets.",
            "",
            f"set_code: {set_code}",
            "era_block: sm",
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
