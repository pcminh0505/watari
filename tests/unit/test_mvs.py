"""Unit tests for ``pokeprice_core.mvs``.

These cover the SQL shape emitted by :func:`refresh_price_mvs` and the
short-circuit logic in :func:`refresh_price_mvs_if_needed`. We deliberately
don't spin up a real Postgres — shape/ordering/skip-conditions are the
interesting invariants; the actual ``REFRESH MATERIALIZED VIEW`` command
is one line and trivially verified by the E2E smoke run.
"""

from __future__ import annotations

from typing import Any

import pytest
from pokeprice_core import mvs


class _FakeSession:
    """Captures execute() + commit() calls on a fake async session."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.commits: int = 0

    async def execute(self, stmt: Any) -> None:
        self.statements.append(str(stmt))

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_refresh_price_mvs_concurrent_emits_three_statements_in_order() -> None:
    session = _FakeSession()
    refreshed = await mvs.refresh_price_mvs(session)  # type: ignore[arg-type]

    assert refreshed == list(mvs.PRICE_MVS)
    assert refreshed == [
        "mv_latest_price",
        "mv_median_7d",
        "mv_cross_source_spread",
    ]
    assert len(session.statements) == 3
    assert session.commits == 3  # one commit per MV so locks release between views
    for stmt, mv in zip(session.statements, mvs.PRICE_MVS, strict=True):
        assert stmt == f"REFRESH MATERIALIZED VIEW CONCURRENTLY {mv}"


@pytest.mark.asyncio
async def test_refresh_price_mvs_non_concurrent_omits_keyword() -> None:
    session = _FakeSession()
    await mvs.refresh_price_mvs(session, concurrently=False)  # type: ignore[arg-type]

    for stmt in session.statements:
        assert " CONCURRENTLY " not in stmt
        assert stmt.startswith("REFRESH MATERIALIZED VIEW ")


@pytest.mark.asyncio
async def test_if_needed_skips_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    async def _boom(*_: Any, **__: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(mvs, "refresh_price_mvs", _boom)

    result = await mvs.refresh_price_mvs_if_needed(rows_written=100, dry_run=True)

    assert result == []
    assert called is False


@pytest.mark.asyncio
async def test_if_needed_skips_zero_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    async def _boom(*_: Any, **__: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(mvs, "refresh_price_mvs", _boom)

    result = await mvs.refresh_price_mvs_if_needed(rows_written=0)

    assert result == []
    assert called is False


@pytest.mark.asyncio
async def test_if_needed_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed refresh must never abort the scrape pipeline."""

    class _FakeFactory:
        def __call__(self) -> _FakeFactory:
            return self

        async def __aenter__(self) -> _FakeSession:
            return _FakeSession()

        async def __aexit__(self, *args: Any) -> None:
            return None

    monkeypatch.setattr(
        "pokeprice_core.db.async_session_factory",
        _FakeFactory(),
    )

    async def _broken(*_: Any, **__: Any) -> list[str]:
        raise RuntimeError("simulated redis/postgres death")

    monkeypatch.setattr(mvs, "refresh_price_mvs", _broken)

    result = await mvs.refresh_price_mvs_if_needed(rows_written=42)

    assert result == []
