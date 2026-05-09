"""Channel-agnostic per-turn orchestrator.

Every customer-facing channel (website chat, WhatsApp, Instagram DMs, on-site
widget) routes one inbound message at a time through this orchestrator. The
orchestrator:

  1. Loads or creates the session for ``(channel, external_id)``.
  2. Pulls the recent conversation history from ``sessions.state``.
  3. Calls :class:`ClaudeBridge` with the runtime persona.
  4. Lints the reply against the brand-voice rules.
  5. Persists the new turn + audit log records.
  6. Returns the reply (and any voice warnings) to the caller.

Channel handlers are responsible for the channel-specific I/O (sending the
reply via WhatsApp / IG / web response). The orchestrator is otherwise
identical for all of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.agents.claude_bridge import ClaudeBridge, ClaudeBridgeError
from src.core.logging import get_logger
from src.core.voice import LintRequest, Violation, lint
from src.storage import sessions
from src.storage.audit import record

log = get_logger(__name__)

HISTORY_TURN_CAP = 12  # bridge will further cap; this caps what we persist too
HISTORY_PERSIST_CAP = 24  # keep more in storage than we feed to the bridge


@dataclass(slots=True)
class TurnRequest:
    channel: str  # website | whatsapp | instagram | telegram | gb
    external_id: str  # platform-specific id (chat id, phone, thread id)
    user_message: str
    require_closing_pattern: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TurnReply:
    session_id: str
    reply: str
    voice_warnings: list[Violation] = field(default_factory=list)


class OrchestratorError(RuntimeError):
    """Raised when the orchestrator can't produce a customer-visible reply."""


@dataclass(slots=True)
class Orchestrator:
    bridge: ClaudeBridge

    async def run(self, request: TurnRequest) -> TurnReply:
        session = await sessions.get_or_create(request.channel, request.external_id)
        history = list(session.state.get("messages", []))[-HISTORY_TURN_CAP:]

        await record(
            "user",
            "inbound",
            {"channel": request.channel, "text": request.user_message},
            session_id=session.id,
        )

        try:
            raw_reply = await self.bridge.query(request.user_message, history=history)
        except ClaudeBridgeError as exc:
            log.error(
                "orchestrator.bridge_failed",
                channel=request.channel,
                err=str(exc),
            )
            await record(
                "system",
                "error",
                {"reason": "bridge_failed", "detail": str(exc)[:200]},
                session_id=session.id,
            )
            raise OrchestratorError(str(exc)) from exc

        reply = (raw_reply or "").strip() or "(no response)"
        violations = lint(
            LintRequest(
                text=reply,
                require_closing_pattern=request.require_closing_pattern,
                channel=request.channel,
            )
        )
        if violations:
            log.warning(
                "voice.violations",
                channel=request.channel,
                count=len(violations),
                rules=[v.rule_id for v in violations],
            )

        await _append_history(session.id, history, request.user_message, reply)
        await record(
            "agent",
            "outbound",
            {
                "channel": request.channel,
                "text": reply,
                "voice_warnings": [v.rule_id for v in violations],
            },
            session_id=session.id,
        )

        return TurnReply(
            session_id=session.id,
            reply=reply,
            voice_warnings=violations,
        )


async def _append_history(
    session_id: str,
    history: list[dict[str, Any]],
    user_text: str,
    assistant_text: str,
) -> None:
    new_history = [
        *history,
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": assistant_text},
    ]
    capped = new_history[-HISTORY_PERSIST_CAP:]
    await sessions.merge_state(session_id, {"messages": capped})
