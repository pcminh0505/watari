"""Filesystem layout helpers for the catalog data tree.

The data tree is a sibling of the package source (not inside it) so we
can edit/diff YML files in reviews without Python caching shenanigans::

    packages/catalog/
    ├── watari_catalog/   ← Python code
    └── data/
        ├── sets/            ← one YML per set
        │   ├── SV2A.yml
        │   └── ...
        └── cards/           ← one YML per (set, local_id)
            ├── SV2A/
            │   ├── 001.yml
            │   └── ...
            └── M2A/
                └── ...
"""

from __future__ import annotations

import pathlib

_PACKAGE_ROOT = pathlib.Path(__file__).resolve().parent.parent  # packages/catalog/


def data_dir() -> pathlib.Path:
    return _PACKAGE_ROOT / "data"


def sets_dir() -> pathlib.Path:
    return data_dir() / "sets"


def cards_dir() -> pathlib.Path:
    return data_dir() / "cards"


def cards_set_dir(set_code: str) -> pathlib.Path:
    """Directory holding per-card YMLs for a given set (uppercase set code)."""
    return cards_dir() / set_code.upper()


def card_yaml_path(set_code: str, local_id_padded: str) -> pathlib.Path:
    """Path of a single card YML, e.g. ``data/cards/SV2A/089.yml``."""
    return cards_set_dir(set_code) / f"{local_id_padded}.yml"
