"""Always-on supervisor for :class:`~src.world.poller.WorldPoller`.

The poller itself is a one-shot drain: it returns when ``max_events`` is
hit, the scenario reports finished, or it sees a burst of consecutive
errors. For the bot process we want the poller to live for the whole
session — pulling ``world_next_event`` continuously so any inbound
WhatsApp / Instagram message the simulator emits gets routed through the
customer-facing orchestrator and replied to in real time.

This module wraps :class:`WorldPoller` in a restart loop with bounded
exponential backoff. Cancelling the supervised task stops the inner
poller cleanly via ``poller.stop()`` and exits.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from src.core.logging import get_logger
from src.workflows.orchestrator import Orchestrator
from src.world.poller import WorldPoller

log = get_logger(__name__)

# Bounds for the restart backoff. Start small (transient MCP blips) and
# grow to a ceiling so we don't hammer a broken upstream.
MIN_RESTART_BACKOFF_S = 1.0
MAX_RESTART_BACKOFF_S = 30.0


@dataclass(slots=True)
class WorldRunner:
    """Long-lived poller supervisor.

    Construct with the same MCP client + orchestrator the rest of the
    bot uses, then call :meth:`run`. The supervisor loops forever
    (until cancelled) restarting the inner :class:`WorldPoller` whenever
    it returns or raises.
    """

    mcp: object  # HappycakeMcpClient — typed loosely to avoid an import cycle
    orchestrator: Orchestrator
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep
    _poller: WorldPoller | None = None
    _stop: bool = False

    def stop(self) -> None:
        self._stop = True
        if self._poller is not None:
            self._poller.stop()

    async def run(self) -> None:
        """Run the poller forever, restarting on error or quiet exit."""
        backoff = MIN_RESTART_BACKOFF_S
        while not self._stop:
            self._poller = WorldPoller(
                mcp=self.mcp,  # type: ignore[arg-type]
                orchestrator=self.orchestrator,
                max_events=None,
            )
            events_in_cycle = 0
            try:
                async with self._poller as poller:
                    result = await poller.run()
                    events_in_cycle = result.events_processed
                    log.info(
                        "world.runner.cycle_done",
                        events=result.events_processed,
                        errors=result.consecutive_errors,
                        finished=result.finished,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                log.exception("world.runner.cycle_failed", err=str(exc))

            # ``stop()`` may have flipped ``_stop`` from another task while
            # we were inside the cycle above; re-check before sleeping.
            if bool(self._stop):
                break

            # Reset backoff on any progress; otherwise grow it so a
            # sustained outage doesn't busy-loop.
            backoff = (
                MIN_RESTART_BACKOFF_S
                if events_in_cycle > 0
                else min(backoff * 2, MAX_RESTART_BACKOFF_S)
            )
            await self.sleeper(backoff)

        log.info("world.runner.stopped")
