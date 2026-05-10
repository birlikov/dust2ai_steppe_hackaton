"""Direct-channel inbound poller — sibling to :mod:`src.world.poller`.

The world-engine poller covers events ``world_next_event`` emits. Channel-level
test helpers like ``whatsapp_inject_inbound`` and seeded GB reviews write
*directly* to the channel store (``whatsapp_list_threads``,
``instagram_list_dm_threads``, ``gb_list_pending_reviews``) without going
through the world queue. Without this poller, real customer-shaped traffic on
WhatsApp / Instagram DMs / Google Business reviews piles up unanswered.

Design (mirrored from ``WorldPoller``):

* High-water mark = startup time per channel; older inbounds are skipped
  forever (the sandbox ships with stale traffic we must not auto-reply to).
* Idempotency by ``channel:thread:msg`` triple — TTL 24h.
* Per-thread ``asyncio.Lock`` so a slow LLM call can't be double-dispatched.
* Channel isolation — each ``_poll_*`` is independently wrapped.
* Inter-outbound sleep dodges any sandbox rate limit.
* Defensive payload reading — list tools serve flat ``inbound`` arrays or
  threaded ``threads[].messages[]`` shapes; both are flattened.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.core.logging import get_logger
from src.mcp.http_client import (
    HappycakeMcpClient,
    McpError,
    McpTransportError,
    call_with_retry,
)
from src.storage import idempotency
from src.storage.audit import record
from src.workflows.orchestrator import (
    Orchestrator,
    OrchestratorError,
    TurnReply,
    TurnRequest,
)

log = get_logger(__name__)

# Backoff after a transport-level error talking to the MCP server.
ERROR_BACKOFF_S = 2.0

# Idempotency TTL — 24h is plenty given a single hackathon run.
_IDEMPOTENCY_TTL_S = 86400

# Channel labels (kept here so test authors can assert on the dispatch dict).
_CH_WHATSAPP = "whatsapp"
_CH_INSTAGRAM = "instagram"
_CH_GB = "gb"


@dataclass(slots=True)
class ChannelRunner:
    """Polls channel list tools for fresh inbounds and routes them through
    the orchestrator + outbound MCP tool. Sibling to :class:`WorldPoller`."""

    mcp: HappycakeMcpClient
    orchestrator: Orchestrator
    interval_s: float = 30.0
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep
    inter_outbound_sleep_s: float = 0.5
    _stop: bool = False
    _high_water: dict[str, str] = field(default_factory=dict)
    _thread_locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def stop(self) -> None:
        """Request a clean shutdown; the next loop iteration will exit."""
        self._stop = True

    async def run(self) -> None:
        """Init high-water marks (= now per channel), then poll forever."""
        await self._init_high_water()
        while not self._stop:
            try:
                counts = await self._cycle()
            except Exception as exc:
                # Last-resort safety net — a bug in a handler must not kill
                # the loop. Log and back off.
                log.exception("channel.cycle_crashed", err=str(exc))
                await self.sleeper(ERROR_BACKOFF_S)
                continue
            log.debug("channel.cycle_done", counts=counts)
            await self.sleeper(self.interval_s)

    async def _init_high_water(self) -> None:
        """Stamp ``now()`` for every channel we poll. Older inbounds are
        skipped forever — the sandbox is seeded with stale traffic that
        we must not auto-reply to."""
        now_iso = datetime.now(UTC).isoformat()
        for ch in (_CH_WHATSAPP, _CH_INSTAGRAM, _CH_GB):
            self._high_water.setdefault(ch, now_iso)
        log.info("channel.high_water_initialized", marks=dict(self._high_water))

    async def _cycle(self) -> dict[str, int]:
        """One pass over all three channels. Returns dispatched counts."""
        wa = await self._poll_whatsapp()
        ig = await self._poll_instagram_dms()
        gb = await self._poll_gb_reviews()
        return {_CH_WHATSAPP: wa, _CH_INSTAGRAM: ig, _CH_GB: gb}

    async def _poll_whatsapp(self) -> int:
        try:
            payload = await call_with_retry(self.mcp, "whatsapp_list_threads", {})
        except (McpTransportError, McpError) as exc:
            log.error("channel.whatsapp_list_failed", err=str(exc))
            return 0

        items = _flatten_inbounds(payload)
        dispatched = 0
        for item in items:
            try:
                if await self._dispatch_whatsapp(item):
                    dispatched += 1
                    await self.sleeper(self.inter_outbound_sleep_s)
            except Exception as exc:
                log.exception(
                    "channel.whatsapp_dispatch_crashed",
                    err=str(exc),
                    item=_safe_id(item),
                )
        return dispatched

    async def _dispatch_whatsapp(  # noqa: PLR0911 — guard chain by design
        self, item: Mapping[str, Any]
    ) -> bool:
        ts = _first(item, "createdAt", "timestamp", "ts", "time")
        msg_id = _first(item, "id", "messageId", "msgId")
        sender = _first(item, "from", "fromExternalId", "phone", "fromPhone")
        text = _first(item, "text", "message", "body")
        if not _is_fresh(ts, self._high_water.get(_CH_WHATSAPP)):
            return False
        if not msg_id or not sender or not text:
            log.info(
                "channel.whatsapp_skip",
                reason="missing id/sender/text",
                item=_safe_id(item),
            )
            return False

        thread_id = str(_first(item, "thread", "threadId", "thread_id") or sender)
        key = _idempotency_key(_CH_WHATSAPP, thread_id, str(msg_id))
        if await idempotency.get(key) is not None:
            return False

        async with self._thread_lock(f"{_CH_WHATSAPP}:{thread_id}"):
            if await idempotency.get(key) is not None:
                return False
            turn = await self._run_orchestrator(_CH_WHATSAPP, str(sender), str(text))
            if turn is None:
                return False
            sent = await self._send_safe(
                "whatsapp_send",
                {"to": str(sender), "message": turn.reply},
                channel=_CH_WHATSAPP,
                thread_id=thread_id,
            )
            if not sent:
                return False
            await self._persist_dispatch(_CH_WHATSAPP, thread_id, key, turn.reply)
            return True

    async def _poll_instagram_dms(self) -> int:
        try:
            payload = await call_with_retry(
                self.mcp, "instagram_list_dm_threads", {}
            )
        except (McpTransportError, McpError) as exc:
            log.error("channel.instagram_list_failed", err=str(exc))
            return 0

        items = _flatten_inbounds(payload)
        dispatched = 0
        for item in items:
            try:
                if await self._dispatch_instagram(item):
                    dispatched += 1
                    await self.sleeper(self.inter_outbound_sleep_s)
            except Exception as exc:
                log.exception(
                    "channel.instagram_dispatch_crashed",
                    err=str(exc),
                    item=_safe_id(item),
                )
        return dispatched

    async def _dispatch_instagram(  # noqa: PLR0911 — guard chain by design
        self, item: Mapping[str, Any]
    ) -> bool:
        ts = _first(item, "createdAt", "timestamp", "ts", "time")
        msg_id = _first(item, "id", "messageId", "msgId")
        thread_id = _first(item, "threadId", "thread_id", "thread")
        text = _first(item, "text", "message", "body")
        if not _is_fresh(ts, self._high_water.get(_CH_INSTAGRAM)):
            return False
        if not msg_id or not thread_id or not text:
            log.info(
                "channel.instagram_skip",
                reason="missing id/thread/text",
                item=_safe_id(item),
            )
            return False

        key = _idempotency_key(_CH_INSTAGRAM, str(thread_id), str(msg_id))
        if await idempotency.get(key) is not None:
            return False

        async with self._thread_lock(f"{_CH_INSTAGRAM}:{thread_id}"):
            if await idempotency.get(key) is not None:
                return False
            turn = await self._run_orchestrator(
                _CH_INSTAGRAM, f"dm:{thread_id}", str(text)
            )
            if turn is None:
                return False
            sent = await self._send_safe(
                "instagram_send_dm",
                {"threadId": str(thread_id), "message": turn.reply},
                channel=_CH_INSTAGRAM,
                thread_id=str(thread_id),
            )
            if not sent:
                return False
            await self._persist_dispatch(
                _CH_INSTAGRAM, str(thread_id), key, turn.reply
            )
            return True

    async def _poll_gb_reviews(self) -> int:
        try:
            payload = await call_with_retry(
                self.mcp, "gb_list_pending_reviews", {}
            )
        except (McpTransportError, McpError) as exc:
            log.error("channel.gb_list_failed", err=str(exc))
            return 0

        items = _items(payload, "reviews", "inbound", "messages")
        dispatched = 0
        for item in items:
            try:
                if await self._dispatch_gb_review(item):
                    dispatched += 1
                    await self.sleeper(self.inter_outbound_sleep_s)
            except Exception as exc:
                log.exception(
                    "channel.gb_dispatch_crashed",
                    err=str(exc),
                    item=_safe_id(item),
                )
        return dispatched

    async def _dispatch_gb_review(  # noqa: PLR0911 — guard chain by design
        self, item: Mapping[str, Any]
    ) -> bool:
        ts = _first(item, "createdAt", "timestamp", "ts", "time")
        review_id = _first(item, "id", "reviewId")
        text = _first(item, "text", "message", "body")
        if not _is_fresh(ts, self._high_water.get(_CH_GB)):
            return False
        if not review_id or not text:
            log.info(
                "channel.gb_skip",
                reason="missing id/text",
                item=_safe_id(item),
            )
            return False

        key = _idempotency_key(_CH_GB, str(review_id), str(review_id))
        if await idempotency.get(key) is not None:
            return False

        async with self._thread_lock(f"{_CH_GB}:{review_id}"):
            if await idempotency.get(key) is not None:
                return False
            turn = await self._run_orchestrator(
                _CH_GB, f"review:{review_id}", str(text)
            )
            if turn is None:
                return False
            sent = await self._send_safe(
                "gb_simulate_reply",
                {"reviewId": str(review_id), "reply": turn.reply},
                channel=_CH_GB,
                thread_id=str(review_id),
            )
            if not sent:
                return False
            await self._persist_dispatch(
                _CH_GB, str(review_id), key, turn.reply
            )
            return True

    def _thread_lock(self, key: str) -> asyncio.Lock:
        """Return (and lazily create) the per-thread lock."""
        lock = self._thread_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._thread_locks[key] = lock
        return lock

    async def _run_orchestrator(
        self, channel: str, external_id: str, user_message: str
    ) -> TurnReply | None:
        """Run the orchestrator; return ``None`` on failure so the caller
        skips both the outbound send and the idempotency-persist step
        (we want the next cycle to legitimately retry, not mark handled).
        """
        try:
            return await self.orchestrator.run(
                TurnRequest(
                    channel=channel,
                    external_id=external_id,
                    user_message=user_message,
                )
            )
        except OrchestratorError as exc:
            log.error(
                "channel.orchestrator_failed",
                channel=channel,
                external_id=external_id,
                err=str(exc),
            )
            return None

    async def _send_safe(
        self,
        tool: str,
        arguments: Mapping[str, Any],
        *,
        channel: str,
        thread_id: str,
    ) -> bool:
        """Call an outbound tool with retry; log + return False on failure."""
        try:
            await call_with_retry(self.mcp, tool, arguments)
        except (McpTransportError, McpError) as exc:
            log.error(
                "channel.send_failed",
                channel=channel,
                tool=tool,
                thread_id=thread_id,
                err=str(exc),
            )
            return False
        return True

    async def _persist_dispatch(
        self, channel: str, thread_id: str, idem_key: str, reply: str
    ) -> None:
        """Mark the message as handled (idempotency) and record audit."""
        await idempotency.put(
            idem_key,
            scope=f"channel-poller-{channel}",
            result={"sent": True, "thread_id": thread_id},
            ttl_seconds=_IDEMPOTENCY_TTL_S,
        )
        await record(
            actor="agent",
            event_type="outbound",
            payload={
                "channel": channel,
                "thread_id": thread_id,
                "text": reply,
            },
        )


# Defensive payload helpers (mirror world/poller.py patterns).


def _first(payload: Mapping[str, Any], *keys: str) -> Any:
    """Return the first non-empty value in ``payload`` for any of ``keys``."""
    for k in keys:
        v = payload.get(k)
        if v not in (None, ""):
            return v
    return None


def _flatten_inbounds(payload: Any) -> list[Mapping[str, Any]]:
    """Flatten a channel-list response into per-message dicts.

    Handles two server shapes: flat (``{"inbound": [...]}``) and threaded
    (``{"threads": [{"threadId": ..., "messages": [...]}]}``). For threaded
    payloads we fold the parent's identity fields (``threadId``,
    ``fromExternalId``) into each child message without overwriting any
    fields the message itself specifies.
    """
    if isinstance(payload, list):
        return [m for m in payload if isinstance(m, Mapping)]
    if not isinstance(payload, Mapping):
        return []

    flat = payload.get("inbound") or payload.get("messages")
    if isinstance(flat, list):
        return [m for m in flat if isinstance(m, Mapping)]

    threads = payload.get("threads")
    if not isinstance(threads, list):
        return []

    out: list[Mapping[str, Any]] = []
    for thread in threads:
        if not isinstance(thread, Mapping):
            continue
        parent = {
            k: v
            for k, v in thread.items()
            if k
            in (
                "threadId",
                "thread_id",
                "thread",
                "fromExternalId",
                "from",
                "phone",
            )
            and v not in (None, "")
        }
        msgs = thread.get("messages")
        if isinstance(msgs, list):
            for m in msgs:
                if isinstance(m, Mapping):
                    merged: dict[str, Any] = {**parent, **m}
                    out.append(merged)
        elif any(k in thread for k in ("text", "message", "body")):
            # Thread doc itself may carry the inbound payload (no nested list).
            out.append(dict(thread))
    return out


def _items(payload: Any, *keys: str) -> list[Mapping[str, Any]]:
    """Extract a list of dict-shaped messages from a list-tool payload.

    Tolerates the three shapes we've seen in the inventory:

    * ``{"inbound": [{...}], "outbound": [...], "simulated": true}``
    * ``[{...}, {...}]`` (raw list, e.g. ``gb_list_reviews``)
    * ``{"messages": [{...}]}`` / ``{"threads": [{...}]}`` (defensive)
    """
    if isinstance(payload, list):
        return [m for m in payload if isinstance(m, Mapping)]
    if isinstance(payload, Mapping):
        for k in keys:
            v = payload.get(k)
            if isinstance(v, list):
                return [m for m in v if isinstance(m, Mapping)]
    return []


def _is_fresh(ts: Any, high_water: str | None) -> bool:
    """True if ``ts`` strictly post-dates the channel's high-water mark.

    Missing/unparseable ``ts`` => *not fresh* (better skip than spam old
    messages). Missing high-water mark => process everything (only
    happens if a test bypasses ``_init_high_water``).
    """
    if not ts:
        return False
    if not high_water:
        return True
    try:
        ts_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        hw_dt = datetime.fromisoformat(str(high_water).replace("Z", "+00:00"))
    except ValueError:
        log.warning("channel.unparseable_ts", ts=str(ts), high_water=str(high_water))
        return False
    return ts_dt > hw_dt


def _idempotency_key(channel: str, thread_id: str, inbound_msg_id: str) -> str:
    return f"channel:{channel}:thread:{thread_id}:msg:{inbound_msg_id}"


def _safe_id(item: Mapping[str, Any]) -> str:
    """Best-effort identifier for a list item, used in error logs only."""
    for k in ("id", "messageId", "msgId", "reviewId", "threadId"):
        v = item.get(k)
        if v:
            return str(v)
    return "<unknown>"
