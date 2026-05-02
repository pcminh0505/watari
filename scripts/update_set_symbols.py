#!/usr/bin/env python3
"""Rebuild apps/web SET_SYMBOL_URLS from Bulbapedia markdown export.

Usage:
  uv run python scripts/update_set_symbols.py \
    --source "/path/to/List_of_Japanese_Pok_mon_Trading_Card_Game_expansions-0.md"
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import quote, unquote

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_CANDIDATES = [
    ROOT / "tmp" / "List_of_Japanese_Pok_mon_Trading_Card_Game_expansions-0.md",
    Path("/Users/minhpham/.cursor/projects/Users-minhpham-Desktop-watari/uploads/")
    / "List_of_Japanese_Pok_mon_Trading_Card_Game_expansions-0.md",
]
SETS_DIR = ROOT / "packages/catalog/data/sets"
CONSTANTS_PATH = ROOT / "apps/web/src/lib/constants.ts"
BASE_SYMBOL_URL = "https://archives.bulbagarden.net/wiki/Special:FilePath/"

# Known naming mismatches between local set YAML name_ja and Bulbapedia label.
MANUAL_FILENAME_OVERRIDES: dict[str, str] = {
    "M2A": "SetSymbolMEGA_Dream_ex.png",
    "S8A": "SetSymbol25th_Anniversary_Collection.png",
    "SM2P": "SetSymbolFacing_a_New_Trial.png",
    "SM8B": "SetSymbolGX_Ultra_Shiny.png",
    "SMP2": "SetSymbolGreat_Detective_Pikachu.png",
}

ROW_RE = re.compile(r"^\|.*\|$", re.M)
FILE_RE = re.compile(r"/wiki/File:([^)]+?\.png)")
NAME_RE = re.compile(r"([^\[\]|]+?)\[")
JPISH_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]|Pok|VMAX|VSTAR|TAG|GX|SM|SV|S\d")


def _norm_name(value: str) -> str:
    out = value.strip()
    for src, dst in (("•", ""), ("・", ""), (" ", ""), ("　", ""), ("＆", ""), ("&", "")):
        out = out.replace(src, dst)
    return out


def _extract_symbol_files_by_name(markdown: str) -> dict[str, str]:
    name_to_file: dict[str, str] = {}
    for line in ROW_RE.findall(markdown):
        if "SetSymbol" not in line:
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) < 3:
            continue

        has_set_no = bool(re.fullmatch(r"\d+", cols[0]))
        symbol_col = cols[1] if has_set_no else cols[0]
        name_col = cols[3] if has_set_no and len(cols) > 3 else cols[2]

        symbol_files = [unquote(f) for f in FILE_RE.findall(symbol_col)]
        if not symbol_files:
            continue

        names = [n.strip() for n in NAME_RE.findall(name_col)]
        cleaned: list[str] = []
        for n in names:
            n = n.split("](")[0].strip()
            lower = n.lower()
            if lower.startswith("part of") or lower.startswith("parts of"):
                continue
            cleaned.append(n)

        split_names: list[str] = []
        for n in cleaned:
            split_names.extend([p.strip() for p in re.split(r"\s*[•・]\s*", n) if p.strip()])

        jpish_names = [n for n in split_names if JPISH_RE.search(n)]
        if not jpish_names:
            continue

        if len(symbol_files) == 1:
            for n in jpish_names:
                name_to_file[_norm_name(n)] = symbol_files[0]
        else:
            for n, f in zip(jpish_names, symbol_files, strict=False):
                name_to_file[_norm_name(n)] = f
    return name_to_file


def _load_set_name_ja() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(SETS_DIR.glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        code = str(data["set_code"]).upper()
        name_ja = str(data.get("name_ja") or "").strip()
        out[code] = name_ja
    return out


def _build_mapping(markdown: str) -> tuple[dict[str, str], list[str]]:
    name_to_file = _extract_symbol_files_by_name(markdown)
    set_to_name = _load_set_name_ja()

    mapping: dict[str, str] = {}
    unmatched: list[str] = []
    for code, name_ja in sorted(set_to_name.items()):
        filename = MANUAL_FILENAME_OVERRIDES.get(code)
        if not filename:
            filename = name_to_file.get(_norm_name(name_ja))
        if not filename:
            unmatched.append(code)
            continue
        mapping[code] = f"{BASE_SYMBOL_URL}{quote(filename, safe='')}"
    return mapping, unmatched


def _resolve_source(source: Path | None) -> Path:
    if source is not None:
        return source
    for candidate in DEFAULT_SOURCE_CANDIDATES:
        if candidate.exists():
            return candidate
    raise SystemExit(
        "No markdown source found. Pass --source /path/to/List_of_Japanese_...md "
        "or place it at tmp/List_of_Japanese_Pok_mon_Trading_Card_Game_expansions-0.md"
    )


def _replace_constants_block(constants_text: str, mapping: dict[str, str]) -> str:
    start = "export const SET_SYMBOL_URLS: Record<string, string> = {"
    marker = "\nexport const ERA_LABELS:"
    a = constants_text.find(start)
    b = constants_text.find(marker)
    if a == -1 or b == -1 or b <= a:
        raise RuntimeError("Could not locate SET_SYMBOL_URLS block in constants.ts")

    lines = [start]
    for code, url in sorted(mapping.items()):
        lines.append(f'  {code}: "{url}",')
    lines.append("};")
    new_block = "\n".join(lines) + "\n"
    return constants_text[:a] + new_block + constants_text[b + 1 :]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--allow-unmatched", action="store_true")
    args = parser.parse_args()

    source = _resolve_source(args.source)
    markdown = source.read_text(encoding="utf-8")
    mapping, unmatched = _build_mapping(markdown)
    if unmatched and not args.allow_unmatched:
        raise SystemExit(
            "Unmatched set codes; refusing to rewrite constants: "
            + ", ".join(unmatched)
        )

    constants = CONSTANTS_PATH.read_text(encoding="utf-8")
    updated = _replace_constants_block(constants, mapping)
    CONSTANTS_PATH.write_text(updated, encoding="utf-8")

    print(f"updated {CONSTANTS_PATH}")
    print(f"source: {source}")
    print(f"set symbols mapped: {len(mapping)}")
    if unmatched:
        print(f"unmatched set codes ({len(unmatched)}): {', '.join(unmatched)}")


if __name__ == "__main__":
    main()
