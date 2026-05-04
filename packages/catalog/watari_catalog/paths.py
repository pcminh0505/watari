"""Filesystem layout helpers for the catalog data tree.

The data tree is a sibling of the package source (not inside it) so we
can edit/diff YML files in reviews without Python caching shenanigans::

    packages/catalog/
    ├── watari_catalog/   ← Python code
    └── data/
        ├── sets/            ← one YML per set
        │   ├── SV2A.yml
        │   └── ...
        ├── cards/           ← one YML per (set, local_id)
        │   ├── SV2A/
        │   │   ├── 001.yml
        │   │   └── ...
        │   └── M2A/
        │       └── ...
        └── audit/           ← one YML per set per oracle (TCGCollector etc.)
            ├── SV2A.yml
            └── ...

``reports/`` lives at the repo root (sibling of ``packages/``) — it holds
human-facing audit summaries and diff outputs that are regenerated each
time ``audit-current`` / ``audit-diff`` runs.
"""

from __future__ import annotations

import pathlib

_PACKAGE_ROOT = pathlib.Path(__file__).resolve().parent.parent  # packages/catalog/
_REPO_ROOT = _PACKAGE_ROOT.parent.parent  # workspace root (contains packages/, reports/)


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


def audit_dir() -> pathlib.Path:
    """Directory holding per-set sidecar oracle data (TCGCollector etc.)."""
    return data_dir() / "audit"


def audit_yaml_path(set_code: str) -> pathlib.Path:
    """Path of a single set's audit sidecar, e.g. ``data/audit/SV2A.yml``."""
    return audit_dir() / f"{set_code.upper()}.yml"


def reports_dir() -> pathlib.Path:
    """Root-level ``reports/`` directory for audit summaries + diffs."""
    return _REPO_ROOT / "reports"
