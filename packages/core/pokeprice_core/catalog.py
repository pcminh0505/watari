"""Catalog ID helpers.

Two canonical IDs:

- ``artwork_id = jp-{lower(set_code)}-{local_padded}``         (artwork level)
- ``card_id    = {artwork_id}-{variant}``                      (print level)

Rules:

- ``set_code`` is lowercased (e.g. ``sv2a``, ``m2a``).
- ``local_id`` is zero-padded to at least 3 digits when numeric; otherwise
  passed through as-is (preserves promo strings like ``PR-001`` if needed).
- ``variant`` is a stable slug (``normal``, ``master_ball_mirror``, …). Always
  present on a card_id — no "missing variant" form.
"""

from __future__ import annotations

DEFAULT_VARIANT = "normal"
LOCAL_ID_PAD_WIDTH = 3


def pad_local_id(local_id: str) -> str:
    """Zero-pad numeric local_ids to at least 3 digits; pass through otherwise."""
    if local_id.isdigit():
        return local_id.zfill(LOCAL_ID_PAD_WIDTH)
    return local_id


def make_artwork_id(set_code: str, local_id: str) -> str:
    """Build canonical artwork_id.

    >>> make_artwork_id("SV2A", "89")
    'jp-sv2a-089'
    >>> make_artwork_id("M2A", "226")
    'jp-m2a-226'
    """
    return f"jp-{set_code.lower()}-{pad_local_id(local_id)}"


def make_card_id(
    set_code: str,
    local_id: str,
    variant: str = DEFAULT_VARIANT,
) -> str:
    """Build canonical card_id (print level).

    >>> make_card_id("SV2A", "89")
    'jp-sv2a-089-normal'
    >>> make_card_id("sv2a", "163", "master_ball_mirror")
    'jp-sv2a-163-master_ball_mirror'
    >>> make_card_id("M2A", "226", "normal")
    'jp-m2a-226-normal'
    """
    return f"{make_artwork_id(set_code, local_id)}-{variant}"


def artwork_id_for_card(card_id: str) -> str:
    """Strip the variant suffix from a card_id.

    >>> artwork_id_for_card("jp-sv2a-163-master_ball_mirror")
    'jp-sv2a-163'
    """
    set_code, local_id, _variant = parse_card_id(card_id)
    return make_artwork_id(set_code, local_id)


def parse_card_id(card_id: str) -> tuple[str, str, str]:
    """Parse card_id into (set_code_lower, local_id, variant).

    >>> parse_card_id("jp-sv2a-089-normal")
    ('sv2a', '089', 'normal')
    >>> parse_card_id("jp-sv2a-163-master_ball_mirror")
    ('sv2a', '163', 'master_ball_mirror')

    Raises ValueError if format is invalid.
    """
    parts = card_id.split("-", 3)
    if len(parts) != 4 or parts[0] != "jp":
        raise ValueError(
            f"Invalid card_id format: {card_id!r}, "
            "expected 'jp-{set_code}-{local_id}-{variant}'"
        )
    return parts[1], parts[2], parts[3]


def parse_artwork_id(artwork_id: str) -> tuple[str, str]:
    """Parse artwork_id into (set_code_lower, local_id).

    >>> parse_artwork_id("jp-sv2a-089")
    ('sv2a', '089')

    Raises ValueError if format is invalid.
    """
    parts = artwork_id.split("-")
    if len(parts) != 3 or parts[0] != "jp":
        raise ValueError(
            f"Invalid artwork_id format: {artwork_id!r}, "
            "expected 'jp-{set_code}-{local_id}'"
        )
    return parts[1], parts[2]
