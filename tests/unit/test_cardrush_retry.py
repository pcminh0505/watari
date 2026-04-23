"""Unit tests for the Cardrush retry helper."""

from __future__ import annotations

import pytest
from pokeprice_cardrush.retry import TransientError, with_retry


class TestWithRetry:
    async def test_success_first_try(self):
        calls = 0

        async def op() -> str:
            nonlocal calls
            calls += 1
            return "ok"

        result = await with_retry(op, label="t", max_attempts=3, base_delay_sec=0)
        assert result == "ok"
        assert calls == 1

    async def test_retries_on_transient_then_succeeds(self):
        calls = 0

        async def op() -> str:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise TransientError(f"simulated {calls}")
            return "ok"

        result = await with_retry(op, label="t", max_attempts=5, base_delay_sec=0)
        assert result == "ok"
        assert calls == 3

    async def test_gives_up_after_max_attempts(self):
        calls = 0

        async def op() -> str:
            nonlocal calls
            calls += 1
            raise TransientError("always")

        with pytest.raises(TransientError, match="always"):
            await with_retry(op, label="t", max_attempts=3, base_delay_sec=0)
        assert calls == 3

    async def test_non_transient_propagates_immediately(self):
        calls = 0

        async def op() -> str:
            nonlocal calls
            calls += 1
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await with_retry(op, label="t", max_attempts=3, base_delay_sec=0)
        assert calls == 1
