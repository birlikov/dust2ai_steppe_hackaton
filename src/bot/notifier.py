"""Proactive owner-bot notifier.

Async background task that wakes up every ``NOTIFIER_INTERVAL_S`` seconds
(default 1800 / 30 min). Each tick:

  1. Pulls evaluator + kitchen + pending-drafts state.
  2. Diffs against the previous tick's snapshot (kept in
     ``sessions.state`` under ``__notifier__``).
  3. If anything **material** changed (new orders, new pending drafts,
     kitchen capacity tightening, MCP errors recurring), asks the
     owner-bridge for a 1-2 line English update and pushes it to the
     owner's Telegram chat.
  4. If nothing material changed, stays silent — no spam.

The task is cancellation-safe (handles ``CancelledError``) and never
crashes the polling loop on errors — it logs and tries again next tick.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot

from src.agents.claude_bridge import ClaudeBridge, ClaudeBridgeError
from src.core.logging import get_logger
from src.mcp.http_client import (
    HappycakeMcpClient,
    McpError,
    McpTransportError,
    call_with_retry,
)
from src.storage import drafts, sessions

log = get_logger(__name__)

# Threshold below which we flag the kitchen as "filling up".
KITCHEN_LOW_REMAINING = 60  # minutes
NO_NEWS = "nothing urgent"
NOTIFIER_SESSION_KEY = "__notifier__"
INERT_REPLY_PREFIXES = ("nothing urgent", "(no response)", "")


@dataclass(slots=True, frozen=True)
class _Snapshot:
    """The slice of state we diff between ticks."""

    orders: int
    leads: int
    pending_drafts: int
    kitchen_remaining_minutes: int
    audit_calls: int
    captured_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "orders": self.orders,
            "leads": self.leads,
            "pending_drafts": self.pending_drafts,
            "kitchen_remaining_minutes": self.kitchen_remaining_minutes,
            "audit_calls": self.audit_calls,
            "captured_at": self.captured_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> _Snapshot:
        return cls(
            orders=int(data.get("orders", 0)),
            leads=int(data.get("leads", 0)),
            pending_drafts=int(data.get("pending_drafts", 0)),
            kitchen_remaining_minutes=int(data.get("kitchen_remaining_minutes", 0)),
            audit_calls=int(data.get("audit_calls", 0)),
            captured_at=str(data.get("captured_at", "")),
        )


async def run(
    *,
    bot: Bot,
    mcp: HappycakeMcpClient,
    owner_bridge: ClaudeBridge,
    interval_s: int,
    fallback_chat_id: int | None = None,
) -> None:
    """Main loop. Cancellable; handles transient errors silently."""
    log.info("notifier.started", interval_s=interval_s)
    # First tick captures baseline only — no message.
    await _ensure_snapshot(mcp)
    try:
        while True:
            try:
                await asyncio.sleep(interval_s)
            except asyncio.CancelledError:
                log.info("notifier.cancelled")
                raise
            try:
                await _tick(
                    bot=bot,
                    mcp=mcp,
                    owner_bridge=owner_bridge,
                    fallback_chat_id=fallback_chat_id,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("notifier.tick_failed", err=str(exc))
    except asyncio.CancelledError:
        return


async def _ensure_snapshot(mcp: HappycakeMcpClient) -> _Snapshot:
    """Return the persisted snapshot, capturing one if absent."""
    state = await _read_state()
    if state:
        return _Snapshot.from_dict(state)
    snap = await _capture(mcp)
    await _write_state(snap)
    return snap


async def _tick(
    *,
    bot: Bot,
    mcp: HappycakeMcpClient,
    owner_bridge: ClaudeBridge,
    fallback_chat_id: int | None,
) -> None:
    chat_id = await _resolve_owner_chat_id(fallback_chat_id)
    if chat_id is None:
        log.debug("notifier.skip_no_owner")
        return

    previous = await _ensure_snapshot(mcp)
    current = await _capture(mcp)
    diff = _material_diff(previous, current)
    if not diff:
        await _write_state(current)
        log.debug("notifier.idle")
        return

    prose = await _summarise(owner_bridge, previous, current, diff)
    if _is_inert(prose):
        await _write_state(current)
        return
    try:
        await bot.send_message(chat_id, prose)
    except Exception as exc:
        log.warning("notifier.send_failed", err=str(exc))
    await _write_state(current)


async def _resolve_owner_chat_id(fallback: int | None) -> int | None:
    rec = await drafts.get_owner()
    if rec is not None:
        return rec.telegram_chat_id
    return fallback


async def _capture(mcp: HappycakeMcpClient) -> _Snapshot:
    pending = await drafts.list_status("pending")
    evidence = await _safe(mcp, "evaluator_get_evidence_summary")
    capacity = await _safe(mcp, "kitchen_get_capacity")
    counts = (evidence or {}).get("counts", {}) if isinstance(evidence, dict) else {}
    remaining = (
        int(capacity.get("remainingCapacityMinutes", 0))
        if isinstance(capacity, dict)
        else 0
    )
    return _Snapshot(
        orders=int(counts.get("squareOrders", 0)),
        leads=int(counts.get("marketingLeads", 0)),
        pending_drafts=len(pending),
        kitchen_remaining_minutes=remaining,
        audit_calls=int(counts.get("auditCalls", 0)),
        captured_at=datetime.now(UTC).isoformat(),
    )


def _material_diff(previous: _Snapshot, current: _Snapshot) -> dict[str, Any]:
    """Return a diff dict of *material* deltas; empty if nothing matters."""
    delta: dict[str, Any] = {}
    if current.orders > previous.orders:
        delta["new_orders"] = current.orders - previous.orders
    if current.leads > previous.leads:
        delta["new_leads"] = current.leads - previous.leads
    if current.pending_drafts > previous.pending_drafts:
        delta["new_pending_drafts"] = (
            current.pending_drafts - previous.pending_drafts
        )
    if (
        current.kitchen_remaining_minutes < KITCHEN_LOW_REMAINING
        and previous.kitchen_remaining_minutes >= KITCHEN_LOW_REMAINING
    ):
        delta["kitchen_filling_up"] = current.kitchen_remaining_minutes
    if delta:
        delta["totals_now"] = {
            "orders": current.orders,
            "leads": current.leads,
            "pending_drafts": current.pending_drafts,
            "kitchen_remaining_minutes": current.kitchen_remaining_minutes,
        }
    return delta


async def _summarise(
    owner_bridge: ClaudeBridge,
    previous: _Snapshot,
    current: _Snapshot,
    diff: dict[str, Any],
) -> str:
    payload = {
        "since": previous.captured_at,
        "now": current.captured_at,
        "what_changed": diff,
    }
    instruction = (
        "Proactive update for Askhat (the owner) on Telegram. Two lines max, "
        "plain English. Lead with what changed since last check. If something "
        "needs his attention, say 'Heads up:' and name it. If nothing actually "
        "matters, just reply with 'nothing urgent'. Do not paste JSON. Do not "
        "use code blocks."
    )
    body = (
        f"{instruction}\n\n"
        "Here is the data (JSON; do NOT echo it back):\n"
        f"{json.dumps(payload, default=str)[:3000]}"
    )
    try:
        reply = await owner_bridge.query(body)
    except ClaudeBridgeError as exc:
        log.warning("notifier.bridge_failed", err=str(exc))
        return ""
    return reply.strip()


def _is_inert(prose: str) -> bool:
    lowered = prose.lower().strip()
    return any(lowered.startswith(p) for p in INERT_REPLY_PREFIXES)


async def _safe(mcp: HappycakeMcpClient, tool: str) -> Any:
    try:
        return await call_with_retry(mcp, tool, {})
    except (McpTransportError, McpError) as exc:
        log.warning("notifier.read_failed", tool=tool, err=str(exc))
        return None


# ---------------------------------------------------------------------------
# Snapshot persistence — single special "session" row keyed by NOTIFIER_SESSION_KEY
# ---------------------------------------------------------------------------


async def _read_state() -> dict[str, Any] | None:
    sess = await sessions.get_or_create("system", NOTIFIER_SESSION_KEY)
    return sess.state.get("snapshot") if sess.state else None


async def _write_state(snap: _Snapshot) -> None:
    sess = await sessions.get_or_create("system", NOTIFIER_SESSION_KEY)
    await sessions.merge_state(sess.id, {"snapshot": snap.to_dict()})
