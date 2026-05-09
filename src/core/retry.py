"""Async retry helper with exponential backoff + jitter.

Used by the world poller, MCP HTTP calls, and the bridge wherever a transient
remote failure is recoverable. Failures that should NOT be retried (e.g.
``ValueError`` from validation) raise out of the helper unchanged — pass the
narrow ``retry_on`` tuple to scope it.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

from src.core.logging import get_logger

log = get_logger(__name__)

DEFAULT_ATTEMPTS = 3
DEFAULT_BASE_DELAY_S = 0.2
DEFAULT_MAX_DELAY_S = 4.0
DEFAULT_JITTER_FRAC = 0.25


class RetryError(RuntimeError):
    """All attempts of a retried call failed. ``__cause__`` is the last error."""


async def with_retry[T](
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay_s: float = DEFAULT_BASE_DELAY_S,
    max_delay_s: float = DEFAULT_MAX_DELAY_S,
    jitter_frac: float = DEFAULT_JITTER_FRAC,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    label: str = "task",
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rng: Callable[[], float] = random.random,
) -> T:
    """Run ``fn`` up to ``attempts`` times with exponential backoff + jitter.

    The delay before attempt ``n`` (1-indexed) is roughly
    ``min(base * 2 ** (n-1), max) * (1 ± jitter_frac)``. ``sleeper`` and ``rng``
    are injected so tests can run deterministically without sleeping.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    if not isinstance(retry_on, tuple) or not retry_on:
        raise TypeError("retry_on must be a non-empty tuple of exception types")

    last_exc: BaseException | None = None
    for attempt_index in range(1, attempts + 1):
        try:
            return await fn()
        except retry_on as exc:
            last_exc = exc
            if attempt_index == attempts:
                break
            delay = _compute_delay(
                attempt_index=attempt_index,
                base=base_delay_s,
                cap=max_delay_s,
                jitter_frac=jitter_frac,
                rng=rng,
            )
            log.warning(
                "retry.backoff",
                label=label,
                attempt=attempt_index,
                next_delay_s=round(delay, 3),
                err=str(exc)[:200],
            )
            await sleeper(delay)

    raise RetryError(f"{label}: failed after {attempts} attempts") from last_exc


def _compute_delay(
    *,
    attempt_index: int,
    base: float,
    cap: float,
    jitter_frac: float,
    rng: Callable[[], float],
) -> float:
    raw = float(base * (2 ** (attempt_index - 1)))
    bounded = float(min(raw, cap))
    if jitter_frac <= 0:
        return bounded
    jitter = bounded * jitter_frac * (2.0 * float(rng()) - 1.0)
    return float(max(0.0, bounded + jitter))
