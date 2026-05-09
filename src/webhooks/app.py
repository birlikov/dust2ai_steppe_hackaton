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

import hashlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.agents.claude_bridge import build_default_bridge
from src.core.config import REPO_ROOT, get_settings
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
from src.webhooks.storefront import (
    lookup_kitchen_product,
    lookup_variation,
    policies_payload,
    shape_catalog,
)
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


# --- /api/order — real order creation against the simulator ----------------


class OrderItem(BaseModel):
    slug: str = Field(min_length=1, max_length=120)
    quantity: int = Field(ge=1, le=20)


class OrderCustomer(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    contact: str = Field(min_length=3, max_length=200)
    channel_preference: str | None = Field(default=None, max_length=40)


class OrderFulfillment(BaseModel):
    type: str = Field(default="pickup", pattern="^(pickup|delivery)$")
    at_iso: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=500)


class OrderRequest(BaseModel):
    items: list[OrderItem] = Field(min_length=1, max_length=12)
    customer: OrderCustomer
    fulfillment: OrderFulfillment = Field(default_factory=OrderFulfillment)
    source: str = Field(default="website", pattern="^(website|agent|telegram|walk-in)$")
    idempotency_key: str | None = Field(default=None, max_length=120)


class OrderResponse(BaseModel):
    status: str
    order_id: str | None = None
    ticket_id: str | None = None
    ready_at_iso: str | None = None
    total_usd: float | None = None
    estimated_lead_minutes: int | None = None
    message: str | None = None


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

    # OpenAPI is left enabled for agent-friendliness — third-party agents can
    # introspect /openapi.json + /docs to learn the storefront contract without
    # reading docs/CONTRACTS.md.
    app = FastAPI(
        title="HappyCake storefront API",
        version="0.2.0",
        description=(
            "FastAPI backend for the HappyCake storefront and Meta-shaped "
            "webhooks. See docs/CONTRACTS.md for the full request/response "
            "shapes."
        ),
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
    # /api/order — real POS + kitchen creation
    # ------------------------------------------------------------------
    @app.post("/api/order", response_model=OrderResponse)
    async def api_order(payload: OrderRequest) -> JSONResponse:
        client: HappycakeMcpClient | None = getattr(app.state, "mcp_client", None)
        if client is None:
            return JSONResponse(
                status_code=503,
                content=OrderResponse(
                    status="failed",
                    message=(
                        "Ordering is paused — the kitchen system is unreachable. "
                        "Please try again in a moment."
                    ),
                ).model_dump(exclude_none=True),
            )

        # Resolve every slug against a fresh catalog snapshot.
        try:
            raw_catalog = await call_with_retry(client, "square_list_catalog", {})
            kitchen_capacity = await call_with_retry(client, "kitchen_get_capacity", {})
        except (McpTransportError, McpError) as exc:
            log.error("order.catalog_fetch_failed", err=str(exc))
            return JSONResponse(
                status_code=503,
                content=OrderResponse(
                    status="failed",
                    message="Couldn't reach the catalog — try again in a moment.",
                ).model_dump(exclude_none=True),
            )
        catalog = shape_catalog(raw_catalog, kitchen=kitchen_capacity)

        square_items: list[dict[str, Any]] = []
        kitchen_items: list[dict[str, Any]] = []
        total_cents = 0
        max_lead = 0
        for item in payload.items:
            variation_id = lookup_variation(catalog, item.slug)
            kitchen_pid = lookup_kitchen_product(catalog, item.slug)
            if variation_id is None or kitchen_pid is None:
                return JSONResponse(
                    status_code=400,
                    content=OrderResponse(
                        status="failed",
                        message=f"Unknown item: {item.slug!r}.",
                    ).model_dump(exclude_none=True),
                )
            product: dict[str, Any] = next(
                (
                    dict(p)
                    for p in catalog.get("products", [])
                    if isinstance(p, dict) and p.get("slug") == item.slug
                ),
                {},
            )
            price_usd = product.get("priceUsd") or 0
            total_cents += int(price_usd * 100) * item.quantity
            lead = product.get("leadTimeMinutes") or 0
            if isinstance(lead, int) and lead > max_lead:
                max_lead = lead
            square_items.append(
                {"variationId": variation_id, "quantity": item.quantity}
            )
            kitchen_items.append(
                {"productId": kitchen_pid, "quantity": item.quantity}
            )

        idempotency_key = payload.idempotency_key or _derive_order_key(payload)
        customer_note = _compose_customer_note(payload)

        # 1) Create the POS order.
        try:
            order_resp = await call_with_retry(
                client,
                "square_create_order",
                {
                    "items": square_items,
                    "source": payload.source,
                    "customerName": payload.customer.name,
                    "customerNote": customer_note,
                    "idempotencyKey": idempotency_key,
                },
            )
        except (McpTransportError, McpError) as exc:
            log.error("order.square_create_failed", err=str(exc))
            return JSONResponse(
                status_code=502,
                content=OrderResponse(
                    status="failed",
                    message="The kitchen couldn't take the order — please try again.",
                ).model_dump(exclude_none=True),
            )
        order_id = _extract_id(order_resp, "orderId") or _extract_id(order_resp, "id")
        if not order_id:
            log.error("order.square_no_id", raw=str(order_resp)[:200])
            return JSONResponse(
                status_code=502,
                content=OrderResponse(
                    status="failed",
                    message="The order system gave an unexpected response.",
                ).model_dump(exclude_none=True),
            )

        # 2) Hand off to the kitchen.
        ticket_id: str | None = None
        kitchen_status = "confirmed"
        try:
            ticket_resp = await call_with_retry(
                client,
                "kitchen_create_ticket",
                {
                    "orderId": order_id,
                    "customerName": payload.customer.name,
                    "items": kitchen_items,
                    "requestedPickupAt": payload.fulfillment.at_iso,
                    "notes": payload.fulfillment.notes,
                },
            )
            ticket_id = _extract_id(ticket_resp, "ticketId") or _extract_id(ticket_resp, "id")
        except (McpTransportError, McpError) as exc:
            kitchen_status = "kitchen_pending"
            log.warning(
                "order.kitchen_create_failed",
                err=str(exc),
                order_id=order_id,
            )

        # 3) Audit + best-effort owner notify.
        await record(
            "user",
            "inbound",
            {
                "kind": "order",
                "order_id": order_id,
                "ticket_id": ticket_id,
                "source": payload.source,
                "items": [item.model_dump() for item in payload.items],
                "total_cents": total_cents,
            },
        )

        ready_at = payload.fulfillment.at_iso

        return JSONResponse(
            content=OrderResponse(
                status=kitchen_status,
                order_id=order_id,
                ticket_id=ticket_id,
                ready_at_iso=ready_at,
                total_usd=round(total_cents / 100, 2),
                estimated_lead_minutes=max_lead or None,
                message=(
                    "Order received. We'll have it ready as scheduled."
                    if kitchen_status == "confirmed"
                    else "Order recorded; the kitchen ticket will be created shortly."
                ),
            ).model_dump(exclude_none=True)
        )

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

    # Mount the Astro static build last so /api/* and /webhook/* match first.
    # Conditional so unit tests (which don't run `npm run build`) still pass —
    # a missing build silently disables the storefront route, not the API.
    storefront_dir = REPO_ROOT / "web" / "dist"
    if storefront_dir.exists():
        app.mount(
            "/",
            StaticFiles(directory=str(storefront_dir), html=True),
            name="storefront",
        )
        log.info("storefront.mounted", path=str(storefront_dir))
    else:
        log.info("storefront.skipped", reason="web/dist missing — build first")

    return app


def _new_external_id() -> str:
    return str(uuid.uuid4())


def _derive_order_key(payload: OrderRequest) -> str:
    """Compute an idempotency key that survives same-minute retries."""
    bucket = datetime.now(UTC).strftime("%Y%m%dT%H%M")
    summary = "|".join(
        f"{item.slug}x{item.quantity}" for item in payload.items
    )
    raw = f"{bucket}|{payload.customer.contact}|{summary}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _compose_customer_note(payload: OrderRequest) -> str:
    parts: list[str] = [f"{payload.fulfillment.type.title()}"]
    if payload.fulfillment.at_iso:
        parts.append(f"at {payload.fulfillment.at_iso}")
    if payload.customer.channel_preference:
        parts.append(f"reach via {payload.customer.channel_preference}")
    if payload.fulfillment.notes:
        parts.append(payload.fulfillment.notes)
    return ". ".join(parts)


def _extract_id(obj: Any, key: str) -> str | None:
    """Pull an id off either the top level or a nested ``order``/``ticket`` dict."""
    if not isinstance(obj, dict):
        return None
    v = obj.get(key)
    if isinstance(v, str):
        return v
    # The simulator wraps responses: {"mode": "...", "order": {"id": "..."}}
    for nested_key in ("order", "ticket", "data", "result"):
        nested = obj.get(nested_key)
        if isinstance(nested, dict):
            v = nested.get("id") or nested.get(key)
            if isinstance(v, str):
                return v
    # Fallback: a generic top-level "id" if the requested key wasn't found.
    if key != "id":
        v = obj.get("id")
        if isinstance(v, str):
            return v
    return None


app = build_app()
