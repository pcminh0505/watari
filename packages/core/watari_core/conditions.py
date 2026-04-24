"""Condition enum and parsers for Cardrush and SNKRDUNK.

Python members use valid identifiers (``A_MINUS``) while the wire/DB values
are the short Cardrush-style codes (``A-``). Callers should prefer using
``Condition.A`` etc. in code; serialize/compare on ``.value`` (or rely on
``StrEnum`` coercion) when talking to the DB or API clients.
"""

import re
from enum import StrEnum


class Condition(StrEnum):
    """Raw (ungraded) card condition, aligned with Cardrush's A/A-/B/C ladder."""

    A = "A"
    A_MINUS = "A-"
    B = "B"
    C = "C"


# --- Cardrush ---
# Product names contain 〔状態A-〕, 〔状態B〕, etc. Absence of bracket = A.
_CARDRUSH_COND_RE = re.compile(r"〔状態(.+?)〕")
_CARDRUSH_MAP = {
    "A": Condition.A,
    "A-": Condition.A_MINUS,
    "B": Condition.B,
    "B+": Condition.B,
    "B-": Condition.B,
    "C": Condition.C,
    "C+": Condition.C,
    "C-": Condition.C,
}
_GRADED_RE = re.compile(r"【(PSA|BGS|CGC|SGC)\d+】")


def parse_cardrush_condition(name: str) -> tuple[Condition | None, bool]:
    """Returns ``(condition, is_graded)``. ``is_graded=True`` means skip for v1."""
    if _GRADED_RE.search(name):
        return None, True
    m = _CARDRUSH_COND_RE.search(name)
    if not m:
        return Condition.A, False
    raw = m.group(1).strip()
    return _CARDRUSH_MAP.get(raw), False


# --- SNKRDUNK ---
# API returns "S", "A", "B", "C". Collapse S → A (pack-fresh maps to A).
_SNKRDUNK_MAP = {
    "S": Condition.A,
    "A": Condition.A,
    "B": Condition.B,
    "C": Condition.C,
}


def parse_snkrdunk_condition(api_condition: str) -> Condition | None:
    return _SNKRDUNK_MAP.get(api_condition.strip().upper())
