"""Admin / ops endpoints — not under the locale-prefixed rate-limited router.

``GET /admin/scrape-health`` returns per-set scrape health summary so
operators can quickly spot sets with zero rows, stale data, or consecutive
card failures without digging through logs.

No authentication is required: this is an internal dashboard endpoint
expected to be used only by operators with direct access.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from watari_api.deps import get_session
from watari_api.schemas import ScrapeHealthRow, ScrapeRunSummary

router = APIRouter(prefix="/admin", tags=["admin"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_STALE_DAYS = 7

_HEALTH_SQL = text(
    """
WITH latest_cardrush AS (
    SELECT DISTINCT ON (metadata->>'set_code')
        metadata->>'set_code'   AS set_code,
        started_at,
        finished_at,
        status,
        rows_written
    FROM scrape_runs
    WHERE source = 'cardrush'
      AND metadata->>'set_code' IS NOT NULL
    ORDER BY metadata->>'set_code', started_at DESC
),
latest_snkrdunk AS (
    SELECT DISTINCT ON (LOWER(metadata->>'era'))
        LOWER(metadata->>'era')  AS era_key,
        started_at,
        finished_at,
        status,
        rows_written
    FROM scrape_runs
    WHERE source = 'snkrdunk'
      AND metadata->>'era' IS NOT NULL
    ORDER BY LOWER(metadata->>'era'), started_at DESC
),
failures AS (
    SELECT c.set_code, css.source, COUNT(*) AS cards_failed
    FROM card_scrape_state css
    JOIN cards c ON c.card_id = css.card_id
    WHERE css.consecutive_failures > 0
    GROUP BY c.set_code, css.source
)
SELECT
    s.set_code,
    s.era_block,
    lc.started_at       AS cr_started_at,
    lc.finished_at      AS cr_finished_at,
    lc.status           AS cr_status,
    COALESCE(lc.rows_written, 0)    AS cr_rows_written,
    COALESCE(f_cr.cards_failed, 0)  AS cr_cards_failed,
    ls.started_at       AS sd_started_at,
    ls.finished_at      AS sd_finished_at,
    ls.status           AS sd_status,
    COALESCE(ls.rows_written, 0)    AS sd_rows_written,
    COALESCE(f_sd.cards_failed, 0)  AS sd_cards_failed
FROM sets s
LEFT JOIN latest_cardrush lc
       ON LOWER(lc.set_code) = LOWER(s.set_code)
LEFT JOIN latest_snkrdunk ls
       ON ls.era_key = LOWER(s.set_code)
LEFT JOIN failures f_cr
       ON f_cr.set_code = s.set_code AND f_cr.source = 'cardrush'
LEFT JOIN failures f_sd
       ON f_sd.set_code = s.set_code AND f_sd.source = 'snkrdunk'
WHERE s.language = 'jp'
ORDER BY s.era_block, s.set_code
"""
)


def _derive_warning(
    *,
    cr_started_at: datetime | None,
    cr_finished_at: datetime | None,
    cr_rows_written: int,
    cr_cards_failed: int,
    sd_started_at: datetime | None,
    sd_finished_at: datetime | None,
    sd_rows_written: int,
    sd_cards_failed: int,
    now: datetime,
) -> str | None:
    """Return the most severe warning for a set, or None if healthy."""
    if cr_cards_failed > 0 or sd_cards_failed > 0:
        return "consecutive_failures"

    stale_cutoff = now.timestamp() - _STALE_DAYS * 86400
    cr_stale = cr_finished_at is not None and cr_finished_at.timestamp() < stale_cutoff
    sd_stale = sd_finished_at is not None and sd_finished_at.timestamp() < stale_cutoff

    cr_zero = cr_started_at is not None and cr_rows_written == 0
    sd_zero = sd_started_at is not None and sd_rows_written == 0

    if cr_zero or sd_zero:
        return "zero_rows"
    if cr_stale or sd_stale:
        return "stale_7d"
    return None


@router.get("/scrape-health", response_model=list[ScrapeHealthRow])
async def scrape_health(session: SessionDep) -> Any:
    """Per-set scrape health summary.

    For each JP set returns:
    - Latest Cardrush + SNKRDUNK run metadata (started_at, status, rows_written)
    - Count of cards with consecutive failures per source
    - A ``warning`` flag: ``'consecutive_failures'``, ``'zero_rows'``,
      ``'stale_7d'``, or ``None``

    Sets with no scrape runs yet show null run metadata and no warning
    (they're expected to be unscraped on first deploy).
    """
    rows = (await session.execute(_HEALTH_SQL)).mappings().all()
    now = datetime.now(UTC)
    result: list[ScrapeHealthRow] = []
    for r in rows:
        cr_cards_failed = int(r["cr_cards_failed"] or 0)
        sd_cards_failed = int(r["sd_cards_failed"] or 0)
        cr_rows_written = int(r["cr_rows_written"] or 0)
        sd_rows_written = int(r["sd_rows_written"] or 0)

        warning = _derive_warning(
            cr_started_at=r["cr_started_at"],
            cr_finished_at=r["cr_finished_at"],
            cr_rows_written=cr_rows_written,
            cr_cards_failed=cr_cards_failed,
            sd_started_at=r["sd_started_at"],
            sd_finished_at=r["sd_finished_at"],
            sd_rows_written=sd_rows_written,
            sd_cards_failed=sd_cards_failed,
            now=now,
        )

        result.append(
            ScrapeHealthRow(
                set_code=r["set_code"],
                era_block=r["era_block"],
                cardrush=ScrapeRunSummary(
                    started_at=r["cr_started_at"],
                    status=r["cr_status"],
                    rows_written=cr_rows_written,
                    cards_failed=cr_cards_failed,
                ),
                snkrdunk=ScrapeRunSummary(
                    started_at=r["sd_started_at"],
                    status=r["sd_status"],
                    rows_written=sd_rows_written,
                    cards_failed=sd_cards_failed,
                ),
                warning=warning,
            )
        )
    return result
