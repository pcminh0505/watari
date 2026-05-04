#!/usr/bin/env python3
"""Seed ``tcgcollector_id`` / ``tcgcollector_slug`` into ``data/sets/*.yml``.

This is a one-time helper for Phase 2a of the catalog data-quality audit
(see plans/catalog-data-quality-audit). It walks every set YML and:

1. Adds ``tcgcollector_id`` and ``tcgcollector_slug`` keys (with ``null``
   placeholders) when the file doesn't already define them.
2. Fills in confirmed mappings extracted from the TCGCollector expansion
   list at https://www.tcgcollector.com/expansions/jp.

The remaining ``null`` entries are an explicit todo list for the operator
running ``audit-fetch`` — the scraper errors out clearly on any set that
still has a ``null`` slug, prompting a manual lookup.

Usage::

    uv run python scripts/seed_tcgcollector_slugs.py
"""

from __future__ import annotations

import pathlib
import sys

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import PreservedScalarString  # noqa: F401

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SETS_DIR = REPO_ROOT / "packages" / "catalog" / "data" / "sets"

# Mapping seeded from https://www.tcgcollector.com/expansions/jp.
# Entries verified against the live page on 2026-05-04. Sets we couldn't
# confirm get a ``None`` placeholder so the schema is still in place.
#
# Format: ``set_code -> (numeric_id, slug)`` where both pieces come from the
# canonical URL ``https://www.tcgcollector.com/sets/{id}/{slug}``.
CONFIRMED: dict[str, tuple[str, str]] = {
    # --- Mega Evolution era ----------------------------------------------
    "M2A":   ("11678", "mega-dream-ex"),
    # M1L (Mega Brave), M1S (Mega Symphonia), M2 (Inferno X), M3, M4 — TBD
    # --- Scarlet & Violet era --------------------------------------------
    "SV2A":  ("11575", "pokemon-card-151"),
    "SV3":   ("11578", "ruler-of-the-black-flame"),
    "SV4A":  ("11602", "shiny-treasure-ex"),
    "SV6":   ("11624", "mask-of-change"),
    "SV8":   ("11638", "super-electric-breaker"),
    "SV8A":  ("11640", "terastal-festival-ex"),
    "SV9A":  ("11648", "hot-air-arena"),
    "SV10":  ("11649", "the-glory-of-team-rocket"),
    # --- Sword & Shield era ----------------------------------------------
    "S4":    ("11379", "amazing-volt-tackle"),
    "S4A":   ("11383", "shiny-star-v"),
    "S5I":   ("11387", "single-strike-master"),
    "S5R":   ("11388", "rapid-strike-master"),
    "S7R":   ("11430", "blue-sky-stream"),
    "S8A":   ("11441", "25th-anniversary-collection"),
    # --- Sun & Moon era --------------------------------------------------
    "SM0":   ("11308", "pikachus-new-friends"),
    "SM2K":  ("11170", "islands-await-you"),
    "SM3H":  ("11284", "to-have-seen-the-battle-rainbow"),
    "SM3N":  ("11265", "darkness-that-consumes-light"),
    "SM8B":  ("11217", "gx-ultra-shiny"),
    "SM9B":  ("11203", "full-metal-wall"),
    "SM12A": ("11211", "tag-all-stars"),
    "SMP2":  ("11279", "great-detective-pikachu"),
}


def _read(path: pathlib.Path) -> dict[str, object]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _emit(path: pathlib.Path, doc: dict[str, object]) -> None:
    """Re-emit a set YML preserving the leading comment + key order."""
    text = path.read_text(encoding="utf-8")
    head: list[str] = []
    for line in text.splitlines():
        if line.startswith("#") or line.strip() == "":
            head.append(line)
        else:
            break

    y = YAML()
    y.default_flow_style = False
    y.allow_unicode = True
    y.width = 200

    # Preferred key order for new + existing fields.
    preferred = [
        "set_code",
        "era_block",
        "language",
        "name_ja",
        "name_en",
        "release_date",
        "total",
        "parent_set_code",
        "tcgdex_id",
        "pokellector_slug",
        "tcgcollector_id",
        "tcgcollector_slug",
    ]
    ordered: dict[str, object] = {k: doc[k] for k in preferred if k in doc}
    for k, v in doc.items():
        if k not in ordered:
            ordered[k] = v

    import io

    buf = io.StringIO()
    y.dump(ordered, buf)
    new_text = "\n".join(head).rstrip() + "\n\n" + buf.getvalue()
    if not new_text.endswith("\n"):
        new_text += "\n"
    path.write_text(new_text, encoding="utf-8")


def main() -> int:
    if not SETS_DIR.is_dir():
        print(f"error: {SETS_DIR} does not exist", file=sys.stderr)
        return 2

    written = 0
    seeded = 0
    skipped = 0
    for path in sorted(SETS_DIR.glob("*.yml")):
        doc = _read(path)
        set_code = str(doc.get("set_code", "")).upper()
        if not set_code:
            print(f"  skip {path.name}: no set_code", file=sys.stderr)
            skipped += 1
            continue

        had_id = "tcgcollector_id" in doc
        had_slug = "tcgcollector_slug" in doc

        if set_code in CONFIRMED:
            tcg_id, tcg_slug = CONFIRMED[set_code]
            doc["tcgcollector_id"] = tcg_id
            doc["tcgcollector_slug"] = tcg_slug
            seeded += 1
        else:
            doc.setdefault("tcgcollector_id", None)
            doc.setdefault("tcgcollector_slug", None)

        # Avoid touching files that already had both keys with the same value.
        if had_id and had_slug and set_code not in CONFIRMED:
            continue

        _emit(path, doc)
        written += 1

    print(
        f"seed_tcgcollector_slugs: written={written} seeded={seeded} "
        f"skipped={skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
