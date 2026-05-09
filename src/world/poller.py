"""World-engine event poller — drives the integration backbone of every channel.

The organizer's MCP server exposes a deterministic scenario engine. Calling
``world_next_event`` returns the next inbound event (a WhatsApp message, an
Instagram DM, a comment, a POS reorder, etc.). The poller:

  1. Pulls the next event with retry/backoff.
  2. Dispatches it to a channel-specific handler that runs the orchestrator
     and posts a reply via the matching MCP tool (``whatsapp_send``,
     ``instagram_send_dm``, ``instagram_reply_to_comment``, ...).
  3. Records the raw event in the audit log.
  4. Loops until the scenario reports it is done or the caller asks to stop.

The exact event payload shape is not strictly specified by the recon; this
module reads it defensively (look for common keys, fall through to "ack-and-log"
for unknown shapes). Tests inject a fake event source.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from src.core.logging import get_logger
from src.mcp.http_client import (
    HappycakeMcpClient,
    McpError,
    McpTransportError,
    call_with_retry,
)
from src.storage.audit import record
from src.workflows.orchestrator import (
    Orchestrator,
    OrchestratorError,
    TurnRequest,
)

log = get_logger(__name__)

# When the scenario delivers no event right now, sleep a touch and try again.
EMPTY_BACKOFF_S = 0.5
ERROR_BACKOFF_S = 2.0
MAX_CONSECUTIVE_ERRORS = 5


@dataclass(slots=True)
class PollResult:
    events_processed: int
    consecutive_errors: int
    finished: bool


@dataclass(slots=True)
class WorldPoller:
    mcp: HappycakeMcpClient
    orchestrator: Orchestrator
    max_events: int | None = None
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep
    handlers: dict[str, Callable[[WorldPoller, Mapping[str, Any]], Awaitable[None]]] = field(
        default_factory=dict
    )
    _stop: bool = False

    async def __aenter__(self) -> WorldPoller:
        if not self.handlers:
            self.handlers = default_handlers()
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._stop = True

    def stop(self) -> None:
        self._stop = True

    async def run(self) -> PollResult:
        processed = 0
        errors = 0
        finished = False
        if not self.handlers:
            self.handlers = default_handlers()

        while not self._stop:
            if self.max_events is not None and processed >= self.max_events:
                break
            try:
                event = await call_with_retry(self.mcp, "world_next_event", {})
            except (McpTransportError, McpError) as exc:
                errors += 1
                log.error(
                    "world.next_event_failed", err=str(exc), consecutive=errors
                )
                if errors >= MAX_CONSECUTIVE_ERRORS:
                    break
                await self.sleeper(ERROR_BACKOFF_S)
                continue
            errors = 0

            if event is None or _is_empty(event):
                if _is_finished(event):
                    finished = True
                    break
                await self.sleeper(EMPTY_BACKOFF_S)
                continue

            await record("system", "world_event", _shrink(event))

            channel = _detect_channel(event)
            handler = self.handlers.get(channel) or self.handlers.get("__default__")
            if handler is None:
                log.info("world.unhandled_event", channel=channel)
            else:
                try:
                    await handler(self, event)
                except Exception as exc:
                    log.exception(
                        "world.handler_failed", channel=channel, err=str(exc)
                    )
            processed += 1

        return PollResult(
            events_processed=processed,
            consecutive_errors=errors,
            finished=finished,
        )


# ---------------------------------------------------------------------------
# Channel handlers
# ---------------------------------------------------------------------------


async def _handle_whatsapp(
    poller: WorldPoller, event: Mapping[str, Any]
) -> None:
    payload = _payload(event)
    text = _first(payload, "text", "message", "body")
    sender = _first(payload, "from", "phone", "customer", "fromPhone")
    if not text or not sender:
        log.info("world.whatsapp_skip", reason="missing text/sender")
        return

    try:
        turn = await poller.orchestrator.run(
            TurnRequest(
                channel="whatsapp",
                external_id=str(sender),
                user_message=str(text),
            )
        )
    except OrchestratorError:
        return  # already logged

    try:
        await call_with_retry(
            poller.mcp,
            "whatsapp_send",
            {"to": str(sender), "message": turn.reply},
        )
    except (McpTransportError, McpError) as exc:
        log.error("world.whatsapp_send_failed", err=str(exc))


async def _handle_instagram_dm(
    poller: WorldPoller, event: Mapping[str, Any]
) -> None:
    payload = _payload(event)
    text = _first(payload, "text", "message", "body")
    thread_id = _first(payload, "threadId", "thread_id", "thread")
    if not text or not thread_id:
        log.info("world.ig_dm_skip", reason="missing text/thread")
        return

    try:
        turn = await poller.orchestrator.run(
            TurnRequest(
                channel="instagram",
                external_id=f"dm:{thread_id}",
                user_message=str(text),
            )
        )
    except OrchestratorError:
        return

    try:
        await call_with_retry(
            poller.mcp,
            "instagram_send_dm",
            {"threadId": str(thread_id), "message": turn.reply},
        )
    except (McpTransportError, McpError) as exc:
        log.error("world.ig_dm_send_failed", err=str(exc))


async def _handle_instagram_comment(
    poller: WorldPoller, event: Mapping[str, Any]
) -> None:
    payload = _payload(event)
    text = _first(payload, "text", "message", "body")
    comment_id = _first(payload, "commentId", "comment_id", "id")
    if not text or not comment_id:
        log.info("world.ig_comment_skip", reason="missing text/comment id")
        return

    try:
        turn = await poller.orchestrator.run(
            TurnRequest(
                channel="instagram",
                external_id=f"comment:{comment_id}",
                user_message=str(text),
            )
        )
    except OrchestratorError:
        return

    try:
        await call_with_retry(
            poller.mcp,
            "instagram_reply_to_comment",
            {"commentId": str(comment_id), "message": turn.reply},
        )
    except (McpTransportError, McpError) as exc:
        log.error("world.ig_comment_reply_failed", err=str(exc))


async def _handle_default(_poller: WorldPoller, event: Mapping[str, Any]) -> None:
    log.info("world.event_logged_only", channel=_detect_channel(event))


def default_handlers() -> dict[str, Callable[[WorldPoller, Mapping[str, Any]], Awaitable[None]]]:
    return {
        "whatsapp": _handle_whatsapp,
        "instagram_dm": _handle_instagram_dm,
        "instagram_comment": _handle_instagram_comment,
        "__default__": _handle_default,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    p = event.get("payload")
    if isinstance(p, Mapping):
        return p
    return event


def _first(payload: Mapping[str, Any], *keys: str) -> Any:
    for k in keys:
        v = payload.get(k)
        if v not in (None, ""):
            return v
    return None


def _detect_channel(event: Mapping[str, Any]) -> str:
    raw = (
        event.get("channel")
        or event.get("type")
        or event.get("source")
        or "unknown"
    )
    text = str(raw).lower()
    if "whatsapp" in text:
        return "whatsapp"
    if "instagram" in text and "comment" in text:
        return "instagram_comment"
    if "instagram" in text:
        return "instagram_dm"
    return text or "unknown"


def _is_empty(event: Mapping[str, Any]) -> bool:
    if not event:
        return True
    status = event.get("status")
    if isinstance(status, str) and status.lower() in {"empty", "no_event", "none"}:
        return True
    return (
        event.get("event") is None
        and event.get("payload") is None
        and event.get("type") is None
    )


def _is_finished(event: Mapping[str, Any] | None) -> bool:
    if not event:
        return False
    status = str(event.get("status", "")).lower()
    return status in {"finished", "complete", "done"}


def _shrink(event: Mapping[str, Any]) -> dict[str, Any]:
    """Compress a world event to the bits we want in the audit log."""
    return {
        "channel": _detect_channel(event),
        "type": event.get("type"),
        "id": event.get("id") or event.get("eventId"),
    }
