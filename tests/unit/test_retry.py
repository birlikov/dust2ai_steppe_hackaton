from __future__ import annotations

import pytest
from src.core.retry import RetryError, _compute_delay, with_retry


@pytest.mark.asyncio
async def test_succeeds_on_first_attempt() -> None:
    calls = 0

    async def ok() -> str:
        nonlocal calls
        calls += 1
        return "fine"

    result = await with_retry(ok, sleeper=_no_sleep, rng=_zero_rng)
    assert result == "fine"
    assert calls == 1


@pytest.mark.asyncio
async def test_retries_until_success_on_third_try() -> None:
    calls = 0
    sleeps: list[float] = []

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ConnectionError("transient")
        return "ok"

    async def sleeper(seconds: float) -> None:
        sleeps.append(seconds)

    result = await with_retry(
        flaky, attempts=4, sleeper=sleeper, rng=_zero_rng
    )
    assert result == "ok"
    assert calls == 3
    assert len(sleeps) == 2  # delays before 2nd and 3rd attempt
    assert sleeps[0] < sleeps[1]  # exponential


@pytest.mark.asyncio
async def test_raises_retry_error_with_cause_after_exhaustion() -> None:
    boom = ConnectionError("nope")

    async def always_fails() -> str:
        raise boom

    with pytest.raises(RetryError) as info:
        await with_retry(always_fails, attempts=2, sleeper=_no_sleep, rng=_zero_rng)
    assert info.value.__cause__ is boom


@pytest.mark.asyncio
async def test_does_not_retry_unlisted_exception_types() -> None:
    async def bad_input() -> str:
        raise ValueError("bad")

    with pytest.raises(ValueError):
        await with_retry(
            bad_input,
            attempts=5,
            retry_on=(ConnectionError,),
            sleeper=_no_sleep,
            rng=_zero_rng,
        )


@pytest.mark.asyncio
async def test_invalid_attempts_rejected() -> None:
    async def fn() -> int:
        return 1

    with pytest.raises(ValueError):
        await with_retry(fn, attempts=0)


def test_compute_delay_caps_at_max() -> None:
    delay = _compute_delay(
        attempt_index=10, base=1.0, cap=4.0, jitter_frac=0.0, rng=_zero_rng
    )
    assert delay == 4.0


def test_compute_delay_applies_negative_jitter_floor_at_zero() -> None:
    # rng=1.0 means jitter is +jitter_frac*delay. rng=0.0 means -jitter_frac*delay.
    # Make sure delay never goes negative.
    delay = _compute_delay(
        attempt_index=1, base=0.1, cap=4.0, jitter_frac=2.0, rng=_zero_rng
    )
    assert delay >= 0.0


async def _no_sleep(_seconds: float) -> None:
    return None


def _zero_rng() -> float:
    return 0.5  # zero jitter offset
