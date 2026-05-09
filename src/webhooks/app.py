"""FastAPI app for inbound webhooks **and** the on-site storefront API.

Routes:

  GET  /health                       liveness
  GET  /webhook/{whatsapp|instagram} Meta verification challenge
  POST /webhook/{whatsapp|instagram} signed inbound envelope (audit-logged)
  GET  /api/catalog                  square_list_catalog → contract shape
  GET  /api/policies                 static brandbook-derived policy text
  POST /api/chat                     storefront chat → ClaudeBridge → reply
  POST /api/lead                     order/custom form → leads + owner notify

The catalog/policies/chat/lead routes are read by the Astro storefront under
``web/`` per ``docs/CONTRACTS.md``. The webhook routes are for Meta-shaped
WhatsApp/Instagram envelopes (Phase 2+ wires them to the orchestrator).

The factory takes optional dependencies so tests can inject fakes. In
production, FastAPI's lifespan context constructs a real orchestrator + MCP
client at boot and closes them on shutdown.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from src.agents.claude_bridge import build_default_bridge
from src.core.config import get_settings
from src.core.logging import get_logger
from src.mcp.http_client import (
    HappycakeMcpClient,
    McpError,
    McpTransportError,
    build_default_client,
    call_with_retry,
)
from src.storage import drafts
from src.storage.audit import record
from src.webhooks.security import verify_signature
from src.webhooks.storefront import policies_payload, shape_catalog
from src.workflows.orchestrator import (
    Orchestrator,
    OrchestratorError,
    TurnRequest,
)

log = get_logger(__name__)

CHANNELS = {"whatsapp", "instagram"}


@dataclass(slots=True)
class AppDeps:
    """Pluggable dependencies. Pass to :func:`build_app` for tests."""

    orchestrator: Orchestrator | None = None
    mcp_client: HappycakeMcpClient | None = None
    allowed_origins: tuple[str, ...] = (
        "http://localhost:4321",
        "http://127.0.0.1:4321",
    )


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    history: list[dict[str, str]] | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    voice_warnings: list[str] = Field(default_factory=list)


class LeadRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    contact: str = Field(min_length=3, max_length=200)
    intent: str = Field(min_length=1, max_length=2000)
    channel_preference: str | None = Field(default=None, max_length=40)
    utm_source: str | None = Field(default=None, max_length=80)
    utm_campaign: str | None = Field(default=None, max_length=120)
    page: str | None = Field(default=None, max_length=300)


class LeadResponse(BaseModel):
    status: str
    lead_id: str


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def build_app(deps: AppDeps | None = None) -> FastAPI:  # noqa: PLR0915
    """Construct the FastAPI app. Test code passes ``deps`` to inject fakes."""
    deps = deps or AppDeps()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Production wiring: build a bridge + orchestrator + MCP client if not
        # injected. Each of these has lazy/cached behaviour internally.
        if deps.orchestrator is None:
            try:
                bridge = build_default_bridge()
                app.state.orchestrator = Orchestrator(bridge=bridge)
            except Exception as exc:  # pragma: no cover - boot diagnostics only
                log.error("orchestrator.boot_failed", err=str(exc))
                app.state.orchestrator = None
        else:
            app.state.orchestrator = deps.orchestrator

        if deps.mcp_client is None:
            try:
                app.state.mcp_client = await build_default_client().__aenter__()
                app.state.mcp_owns_client = True
            except Exception as exc:  # pragma: no cover - boot diagnostics only
                log.error("mcp.boot_failed", err=str(exc))
                app.state.mcp_client = None
                app.state.mcp_owns_client = False
        else:
            app.state.mcp_client = deps.mcp_client
            app.state.mcp_owns_client = False

        try:
            yield
        finally:
            if app.state.mcp_owns_client and app.state.mcp_client is not None:
                await app.state.mcp_client.__aexit__(None, None, None)

    app = FastAPI(
        title="hackaton-webhooks",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(deps.allowed_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Hub-Signature-256"],
        allow_credentials=False,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # ------------------------------------------------------------------
    # /api/catalog
    # ------------------------------------------------------------------
    @app.get("/api/catalog")
    async def api_catalog() -> JSONResponse:
        client: HappycakeMcpClient | None = getattr(app.state, "mcp_client", None)
        if client is None:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "catalog_unavailable",
                    "message": "We're updating the menu — try again in a moment.",
                },
            )
        try:
            catalog_raw = await call_with_retry(client, "square_list_catalog", {})
            kitchen_raw = await call_with_retry(client, "kitchen_get_capacity", {})
        except (McpTransportError, McpError) as exc:
            log.error("catalog.fetch_failed", err=str(exc))
            return JSONResponse(
                status_code=503,
                content={
                    "error": "catalog_unavailable",
                    "message": "We're updating the menu — try again in a moment.",
                },
            )
        return JSONResponse(
            content=shape_catalog(catalog_raw, kitchen=kitchen_raw)
        )

    # ------------------------------------------------------------------
    # /api/policies
    # ------------------------------------------------------------------
    @app.get("/api/policies")
    async def api_policies() -> dict[str, Any]:
        return policies_payload()

    # ------------------------------------------------------------------
    # /api/chat
    # ------------------------------------------------------------------
    @app.post("/api/chat", response_model=ChatResponse)
    async def api_chat(payload: ChatRequest) -> ChatResponse:
        orchestrator: Orchestrator | None = getattr(app.state, "orchestrator", None)
        if orchestrator is None:
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "model_unreachable",
                    "message": (
                        "I couldn't reach the team's assistant just now — "
                        "please try again in a moment."
                    ),
                },
            )
        external_id = payload.session_id or _new_external_id()
        try:
            turn = await orchestrator.run(
                TurnRequest(
                    channel="website",
                    external_id=external_id,
                    user_message=payload.message,
                    require_closing_pattern=False,
                )
            )
        except OrchestratorError as exc:
            log.error("api_chat.orchestrator_failed", err=str(exc))
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "model_unreachable",
                    "message": (
                        "I couldn't reach the team's assistant just now — "
                        "please try again in a moment."
                    ),
                },
            ) from exc
        return ChatResponse(
            session_id=external_id,
            reply=turn.reply,
            voice_warnings=[v.rule_id for v in turn.voice_warnings],
        )

    # ------------------------------------------------------------------
    # /api/lead
    # ------------------------------------------------------------------
    @app.post("/api/lead", response_model=LeadResponse)
    async def api_lead(payload: LeadRequest) -> LeadResponse:
        lead = await drafts.insert_lead(
            name=payload.name,
            contact=payload.contact,
            intent=payload.intent,
            channel_preference=payload.channel_preference,
            utm_source=payload.utm_source,
            utm_campaign=payload.utm_campaign,
            page=payload.page,
        )
        await record(
            "user",
            "inbound",
            {
                "kind": "lead",
                "lead_id": lead.id,
                "utm_source": lead.utm_source,
                "utm_campaign": lead.utm_campaign,
                "channel_preference": lead.channel_preference,
            },
        )
        # Best-effort owner notify via marketing_report_to_owner. Non-fatal if
        # MCP is briefly unreachable — the lead is already persisted and the
        # next dashboard check picks it up.
        client: HappycakeMcpClient | None = getattr(app.state, "mcp_client", None)
        if client is not None:
            try:
                await call_with_retry(client, "marketing_report_to_owner", {})
                await drafts.mark_lead_reported(lead.id)
            except (McpTransportError, McpError) as exc:
                log.warning("lead.owner_notify_failed", err=str(exc))
        return LeadResponse(status="received", lead_id=lead.id)

    # ------------------------------------------------------------------
    # Meta-shaped webhooks (kept from Phase 0)
    # ------------------------------------------------------------------
    @app.get("/webhook/{channel}")
    async def verify(
        channel: str,
        request: Request,
    ) -> PlainTextResponse:
        if channel not in CHANNELS:
            raise HTTPException(status_code=404, detail="unknown channel")
        params = request.query_params
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge")
        expected = get_settings().meta_verify_token
        if mode == "subscribe" and token and expected and token == expected:
            return PlainTextResponse(challenge or "")
        raise HTTPException(status_code=403, detail="verify failed")

    @app.post("/webhook/{channel}")
    async def inbound(
        channel: str,
        request: Request,
        x_hub_signature_256: str | None = Header(default=None),
    ) -> dict[str, Any]:
        if channel not in CHANNELS:
            raise HTTPException(status_code=404, detail="unknown channel")
        body = await request.body()
        secret = get_settings().meta_app_secret
        if secret and not verify_signature(secret, body, x_hub_signature_256):
            log.warning("webhook.bad_signature", channel=channel)
            raise HTTPException(status_code=401, detail="bad signature")
        await record(
            "system", "inbound", {"channel": channel, "size": len(body)}
        )
        return {"status": "received"}

    return app


def _new_external_id() -> str:
    return str(uuid.uuid4())


app = build_app()
