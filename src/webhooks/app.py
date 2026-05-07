"""FastAPI webhook receiver for WhatsApp + Instagram.

Routes:
  GET  /health                  → 200 ok
  GET  /webhook/{channel}        → Meta verification challenge
  POST /webhook/{channel}        → inbound message envelope (signed)

The POST handler currently logs+audits and returns 200. Once the agent loop is
wired in (post brief unsealing), the body parser dispatches to the agent and
replies via the configured MessageSender.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse

from src.core.config import get_settings
from src.core.logging import get_logger
from src.storage.audit import record
from src.webhooks.security import verify_signature

log = get_logger(__name__)

CHANNELS = {"whatsapp", "instagram"}


def build_app() -> FastAPI:
    app = FastAPI(title="hackaton-webhooks", docs_url=None, redoc_url=None)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

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

        # NOTE: payload parsing intentionally minimal — extend post-brief.
        await record(
            "system",
            "inbound",
            {"channel": channel, "size": len(body)},
        )
        return {"status": "received"}

    return app


app = build_app()
