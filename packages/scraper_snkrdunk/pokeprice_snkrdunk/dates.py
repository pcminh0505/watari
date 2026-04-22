"""Parse SNKRDUNK Japanese date strings into timezone-aware UTC datetimes.

Handles two formats the site returns:
  * relative: "40分前", "4時間前", "1日前", "2週間前", "3ヶ月前", "1年前"
  * absolute: "2026/03/21"

All output datetimes are in UTC. Relative times are computed from a reference
"now" (defaults to current time) that is converted to JST first to match what
the site is displaying to Japanese users.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

_RELATIVE_RE = re.compile(r"^(\d+)(秒|分|時間|日|週間|ヶ月|年)前$")
_ABSOLUTE_RE = re.compile(r"^(\d{4})/(\d{2})/(\d{2})$")

_SIMPLE_UNITS: dict[str, str] = {
    "秒": "seconds",
    "分": "minutes",
    "時間": "hours",
    "日": "days",
    "週間": "weeks",
}


def parse_snkrdunk_date(value: str, *, now: datetime | None = None) -> datetime:
    """Return a UTC datetime for the given SNKRDUNK date string.

    If the string can't be parsed, the reference `now` (or system now) is
    returned as a conservative fallback.
    """
    s = value.strip()
    reference = (now or datetime.now(tz=JST)).astimezone(JST)

    m = _RELATIVE_RE.match(s)
    if m:
        value_int = int(m.group(1))
        unit = m.group(2)
        if unit in _SIMPLE_UNITS:
            delta = timedelta(**{_SIMPLE_UNITS[unit]: value_int})
        elif unit == "ヶ月":
            delta = timedelta(days=value_int * 30)
        elif unit == "年":
            delta = timedelta(days=value_int * 365)
        else:
            delta = timedelta()
        return (reference - delta).astimezone(timezone.utc)

    m = _ABSOLUTE_RE.match(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return datetime(y, mo, d, tzinfo=JST).astimezone(timezone.utc)

    return reference.astimezone(timezone.utc)
