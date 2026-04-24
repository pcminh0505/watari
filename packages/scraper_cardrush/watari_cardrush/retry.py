"""Small async retry helper with exponential backoff.

We only retry transient network errors here (connection drops, timeouts,
5xx). Business-level failures (404, empty page, parse failure) propagate.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TransientError(Exception):
    """Raise to signal a retryable error from inside a retriable callable."""


async def with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    label: str,
    max_attempts: int = 3,
    base_delay_sec: float = 1.0,
    max_delay_sec: float = 8.0,
    jitter_sec: float = 0.25,
) -> T:
    """Run ``operation`` with exponential backoff on ``TransientError``.

    Non-transient exceptions bubble up on the first attempt.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return await operation()
        except TransientError as exc:
            if attempt >= max_attempts:
                logger.error(
                    "%s: giving up after %d attempts (%s)", label, attempt, exc
                )
                raise
            delay = min(base_delay_sec * (2 ** (attempt - 1)), max_delay_sec)
            delay += random.uniform(0, jitter_sec)
            logger.warning(
                "%s: transient error on attempt %d/%d (%s); retry in %.2fs",
                label,
                attempt,
                max_attempts,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
