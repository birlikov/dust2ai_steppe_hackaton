"""Always-on kitchen-staff side simulation.

The customer-facing flow we control ends at ``kitchen_create_ticket`` —
real bakery staff (or, in the sandbox, this loop) accept the ticket and
later mark it ready. This module closes the loop for the demo so
evaluators see the full *order → ticket → accept → ready* path complete
in real time, including the ``kitchen_*`` evaluator counter increments.

Disabled by default. Enable with ``KITCHEN_AUTO_DEMO=true`` in
``.env``. The supervisor is structurally a sibling of
:class:`src.world.runner.WorldRunner` — same restart-loop shape, same
cancellation semantics.

Behaviour per tick (every ``KITCHEN_TICK_S`` seconds, default 20):

- ``kitchen_list_tickets`` filtered to ``pending``. Each pending ticket
  is **accepted** via ``kitchen_accept_ticket``, *unless* the
  remaining capacity from ``kitchen_get_capacity`` would dip below
  ``KITCHEN_REJECT_THRESHOLD_MIN`` minutes — those get rejected with a
  brand-voice apology note (``kitchen_reject_ticket``).
- ``kitchen_list_tickets`` filtered to ``accepted``. Tickets older than
  their lead-time window are **marked ready** via
  ``kitchen_mark_ready`` so the customer-side ETA is honored.

Best-effort throughout: any tool failure logs and the next tick retries.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from src.core.logging import get_logger
from src.mcp.http_client import (
    HappycakeMcpClient,
    McpError,
    McpTransportError,
    call_with_retry,
)

log = get_logger(__name__)

# Cadence + thresholds. Tuned for a demo: short enough to feel live,
# generous enough that judges have time to see the intermediate states.
DEFAULT_TICK_S: float = 20.0
DEFAULT_REJECT_THRESHOLD_MIN: int = 30  # reject if accepting would push capacity below 30 min
DEFAULT_LEAD_TIME_MIN: int = 10  # if a ticket lacks a lead-time, treat as 10 min for ready-at

# Bounds for the supervisor restart-backoff. Same shape as WorldRunner.
MIN_RESTART_BACKOFF_S = 1.0
MAX_RESTART_BACKOFF_S = 30.0


@dataclass(slots=True)
class KitchenRunner:
    """Long-lived kitchen-staff simulator.

    Construct with the same MCP client the rest of the bot uses; call
    :meth:`run`. The supervisor loops forever (until cancelled) restarting
    the inner tick loop on transient failures.
    """

    mcp: HappycakeMcpClient
    tick_s: float = DEFAULT_TICK_S
    reject_threshold_min: int = DEFAULT_REJECT_THRESHOLD_MIN
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep
    _stop: bool = False

    def stop(self) -> None:
        self._stop = True

    async def run(self) -> None:
        """Tick the kitchen forever, with bounded backoff on errors."""
        backoff = MIN_RESTART_BACKOFF_S
        while not self._stop:
            try:
                accepted, rejected, marked_ready = await self._tick()
                log.info(
                    "kitchen.runner.tick",
                    accepted=accepted,
                    rejected=rejected,
                    marked_ready=marked_ready,
                )
                # Reset backoff on any progress; otherwise sit tight for
                # the normal tick interval.
                if accepted + rejected + marked_ready > 0:
                    backoff = MIN_RESTART_BACKOFF_S
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                log.exception("kitchen.runner.tick_failed", err=str(exc))
                backoff = min(backoff * 2, MAX_RESTART_BACKOFF_S)

            if bool(self._stop):
                break
            # Sleep the longer of (tick_s, backoff) so we don't busy-loop
            # under sustained errors.
            await self.sleeper(max(self.tick_s, backoff))

        log.info("kitchen.runner.stopped")

    async def _tick(self) -> tuple[int, int, int]:
        """One pass over pending + accepted tickets. Returns
        ``(accepted_count, rejected_count, marked_ready_count)``."""
        accepted = rejected = marked_ready = 0

        # 1. Walk pending tickets. Capacity-aware: refuse new ones if
        #    accepting would dip below the reject threshold.
        try:
            pending_resp = await call_with_retry(
                self.mcp, "kitchen_list_tickets", {"status": "pending"}
            )
        except (McpTransportError, McpError) as exc:
            log.warning("kitchen.runner.list_pending_failed", err=str(exc))
            return accepted, rejected, marked_ready

        pending = _coerce_tickets(pending_resp)
        for ticket in pending:
            ticket_id = str(ticket.get("id") or ticket.get("ticketId") or "")
            if not ticket_id:
                continue
            # Re-pull capacity each iteration so a queue of pending tickets
            # naturally throttles itself.
            cap = await self._capacity_remaining_min()
            if cap is not None and cap < self.reject_threshold_min:
                if await self._reject(
                    ticket_id,
                    note=(
                        "Honest no — kitchen is full today. "
                        "Want to set this for tomorrow?"
                    ),
                ):
                    rejected += 1
            elif await self._accept(ticket_id):
                accepted += 1

        # 2. Walk accepted tickets. Mark ready when their nominal lead
        #    time has elapsed since acceptance.
        try:
            accepted_resp = await call_with_retry(
                self.mcp, "kitchen_list_tickets", {"status": "accepted"}
            )
        except (McpTransportError, McpError) as exc:
            log.warning("kitchen.runner.list_accepted_failed", err=str(exc))
            return accepted, rejected, marked_ready

        for ticket in _coerce_tickets(accepted_resp):
            ticket_id = str(ticket.get("id") or ticket.get("ticketId") or "")
            if not ticket_id:
                continue
            if _is_ready_to_mark(ticket) and await self._mark_ready(ticket_id):
                marked_ready += 1

        return accepted, rejected, marked_ready

    # --- single-tool wrappers, all best-effort -----------------------------

    async def _capacity_remaining_min(self) -> int | None:
        try:
            resp = await call_with_retry(self.mcp, "kitchen_get_capacity", {})
        except (McpTransportError, McpError):
            return None
        if isinstance(resp, dict):
            value = resp.get("remainingCapacityMinutes")
            if isinstance(value, int):
                return value
            try:
                return int(float(value)) if value is not None else None
            except (TypeError, ValueError):
                return None
        return None

    async def _accept(self, ticket_id: str) -> bool:
        try:
            await call_with_retry(
                self.mcp,
                "kitchen_accept_ticket",
                {"ticketId": ticket_id, "note": "auto-accepted by demo runner"},
            )
            return True
        except (McpTransportError, McpError) as exc:
            log.warning("kitchen.accept_failed", ticket_id=ticket_id, err=str(exc))
            return False

    async def _reject(self, ticket_id: str, *, note: str) -> bool:
        try:
            await call_with_retry(
                self.mcp,
                "kitchen_reject_ticket",
                {"ticketId": ticket_id, "reason": note},
            )
            return True
        except (McpTransportError, McpError) as exc:
            log.warning("kitchen.reject_failed", ticket_id=ticket_id, err=str(exc))
            return False

    async def _mark_ready(self, ticket_id: str) -> bool:
        try:
            await call_with_retry(
                self.mcp,
                "kitchen_mark_ready",
                {
                    "ticketId": ticket_id,
                    "pickupNote": "Ready at the counter — thanks for waiting.",
                },
            )
            return True
        except (McpTransportError, McpError) as exc:
            log.warning(
                "kitchen.mark_ready_failed", ticket_id=ticket_id, err=str(exc)
            )
            return False


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _coerce_tickets(resp: Any) -> list[dict[str, Any]]:
    """Tolerate either a bare array or a wrapped ``{tickets: [...]}``."""
    if isinstance(resp, list):
        return [t for t in resp if isinstance(t, dict)]
    if isinstance(resp, dict):
        for key in ("tickets", "items", "data"):
            value = resp.get(key)
            if isinstance(value, list):
                return [t for t in value if isinstance(t, dict)]
    return []


def _is_ready_to_mark(ticket: dict[str, Any]) -> bool:
    """Return True if an accepted ticket has been waiting at least its
    nominal lead time and should now be marked ready.
    """
    accepted_at = (
        ticket.get("acceptedAt")
        or ticket.get("accepted_at")
        or ticket.get("createdAt")
    )
    if not accepted_at:
        return False
    try:
        ts = datetime.fromisoformat(str(accepted_at).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return False

    lead_min = ticket.get("leadTimeMinutes") or ticket.get("lead_time_min") or DEFAULT_LEAD_TIME_MIN
    try:
        lead_min_int = int(lead_min)
    except (TypeError, ValueError):
        lead_min_int = DEFAULT_LEAD_TIME_MIN

    elapsed = datetime.now(UTC) - ts
    return elapsed >= timedelta(minutes=lead_min_int)
