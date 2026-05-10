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

import re
from dataclasses import dataclass, field
from typing import Any

from src.agents.claude_bridge import ClaudeBridge, ClaudeBridgeError
from src.core.logging import get_logger
from src.core.voice import LintRequest, Violation, lint
from src.storage import drafts, sessions
from src.storage.audit import record

log = get_logger(__name__)

HISTORY_TURN_CAP = 12  # bridge will further cap; this caps what we persist too
HISTORY_PERSIST_CAP = 24  # keep more in storage than we feed to the bridge

# Phrases the persona uses to defer to the human owner. When any of these
# show up in an outbound reply we drop a pending draft into the owner's
# /inbox so the promise is traceable (otherwise the customer hears
# "we'll get back to you" and nothing actually queues).
_ESCALATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:we'?ll|we will|i'?ll|i will|let me)\s+(?:get|come|circle)\s+back\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\blet me check with (?:the team|saule|the owner)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:i'?ll|i will) (?:ask|check with)\s+(?:the team|saule|the owner)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:we'?ll|i'?ll) (?:reply|respond|follow up)\b", re.IGNORECASE),
    re.compile(r"\bwithin (?:the hour|an hour|24 hours|a day)\b", re.IGNORECASE),
    re.compile(r"\bgetting back to you\b", re.IGNORECASE),
)


def _is_escalation_promise(text: str) -> bool:
    """Return True if the persona's reply commits to a human follow-up."""
    return any(p.search(text) for p in _ESCALATION_PATTERNS)


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

        # When the persona promises a human follow-up ("we'll be back",
        # "let me check with the team"), park a draft in the owner's
        # /inbox so the commitment is traceable. Otherwise the customer
        # hears a promise and nothing queues anywhere.
        if _is_escalation_promise(reply):
            try:
                draft = await drafts.create(
                    channel=request.channel,
                    kind="escalation_callback",
                    payload={
                        "session_id": session.id,
                        "external_id": request.external_id,
                        "user_message": request.user_message,
                        "agent_reply": reply,
                    },
                    idempotency_key=f"escalation:{session.id}",
                )
                log.info(
                    "orchestrator.escalation_drafted",
                    channel=request.channel,
                    session_id=session.id,
                    draft_id=draft.id,
                )
            except Exception as exc:
                # Never let a draft failure block the customer reply.
                log.warning(
                    "orchestrator.escalation_draft_failed",
                    channel=request.channel,
                    err=str(exc),
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
