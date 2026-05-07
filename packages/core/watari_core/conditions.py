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


class GradeCompany(StrEnum):
    """Grading company for certified (slab) cards. SGC is deferred."""

    PSA = "PSA"
    BGS = "BGS"
    CGC = "CGC"


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
# Detects graded listings; supports optional decimal score (e.g. 【BGS9.5】).
_GRADED_RE = re.compile(r"【(PSA|BGS|CGC|SGC)\d+(?:\.\d+)?】")

# Parses a bare grade string like "PSA10" or "BGS9.5". SGC excluded (deferred).
_GRADE_RE = re.compile(r"^(PSA|BGS|CGC)(\d+(?:\.\d+)?)$", re.IGNORECASE)


def parse_cardrush_condition(name: str) -> tuple[Condition | None, bool]:
    """Returns ``(condition, is_graded)``. ``is_graded=True`` means skip for v1."""
    if _GRADED_RE.search(name):
        return None, True
    m = _CARDRUSH_COND_RE.search(name)
    if not m:
        return Condition.A, False
    raw = m.group(1).strip()
    return _CARDRUSH_MAP.get(raw), False


def extract_cardrush_grade(name: str) -> str | None:
    """Return the bare grade string (e.g. ``'PSA10'``, ``'BGS9.5'``) from a
    Cardrush product name, or ``None`` if no graded token is present.

    Strips the ``【…】`` delimiters from the match so the result is suitable
    for passing to :func:`parse_grade_company_score`.
    """
    m = _GRADED_RE.search(name)
    if not m:
        return None
    # m.group(0) is e.g. '【PSA10】'; strip the delimiters.
    return m.group(0)[1:-1]


def parse_grade_company_score(raw: str) -> tuple[GradeCompany, float] | None:
    """Parse a bare grade string into ``(GradeCompany, score)``.

    Returns ``None`` for unknown companies (e.g. SGC) or malformed input.

    Examples::

        parse_grade_company_score("PSA10")   → (GradeCompany.PSA, 10.0)
        parse_grade_company_score("BGS9.5")  → (GradeCompany.BGS, 9.5)
        parse_grade_company_score("SGC10")   → None  (SGC deferred)
    """
    m = _GRADE_RE.match(raw.strip())
    if not m:
        return None
    try:
        company = GradeCompany(m.group(1).upper())
        score = float(m.group(2))
        return (company, score)
    except (ValueError, KeyError):
        return None


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
