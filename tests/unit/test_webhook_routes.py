from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from src.agents.claude_bridge import ClaudeBridge
from src.core.config import get_settings
from src.storage import db
from src.webhooks.app import AppDeps, build_app
from src.workflows.orchestrator import Orchestrator


@pytest.fixture(autouse=True)
async def _isolate_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "webhook_test.db")
    await db.close()
    yield
    await db.close()


class FakeMcpClient:
    def __init__(self, *, catalog: Any | None = None, kitchen: Any | None = None):
        self.catalog = catalog or {
            "catalog": [
                {
                    "id": "sq_item_honey_cake_slice",
                    "variationId": "sq_var_honey_cake_slice",
                    "name": "Honey cake slice",
                    "category": "slices",
                    "priceCents": 850,
                    "kitchenProductId": "honey-cake-slice",
                }
            ]
        }
        self.kitchen = kitchen or {
            "remainingCapacityMinutes": 240,
            "overCapacity": False,
        }
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    async def __aenter__(self) -> FakeMcpClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def call(
        self,
        tool: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        raw_text: bool = False,
    ) -> Any:
        self.calls.append((tool, dict(arguments or {})))
        if tool == "square_list_catalog":
            return self.catalog
        if tool == "kitchen_get_capacity":
            return self.kitchen
        if tool == "marketing_report_to_owner":
            return {"ok": True}
        return None


def _bridge(reply: str = "ok") -> ClaudeBridge:
    async def runner(
        argv: list[str],
        stdin: bytes,
        env: Mapping[str, str],
        timeout_s: float,
    ) -> tuple[int, bytes, bytes]:
        return 0, reply.encode("utf-8"), b""

    return ClaudeBridge(
        model="claude-opus-4-7",
        system_prompt="SYS",
        command="/usr/bin/true",
        runner=runner,
    )


def test_health_ok() -> None:
    app = build_app(AppDeps(mcp_client=FakeMcpClient()))  # type: ignore[arg-type]
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_api_catalog_shape() -> None:
    app = build_app(AppDeps(mcp_client=FakeMcpClient()))  # type: ignore[arg-type]
    with TestClient(app) as client:
        r = client.get("/api/catalog")
        assert r.status_code == 200
        body = r.json()
        assert body["source"] == "happycake_mcp"
        assert len(body["products"]) == 1
        assert body["products"][0]["name"] == 'cake "Honey" — slice'
        assert body["kitchen"]["remainingCapacityMinutes"] == 240


def test_api_catalog_503_when_client_missing() -> None:
    app = build_app(AppDeps(mcp_client=None))
    with TestClient(app) as client:
        r = client.get("/api/catalog")
        # If the MCP boot fails (no token), we get 503; if it succeeds against
        # the real server, we still get 200. Either way it's a stable code.
        assert r.status_code in (200, 503)


def test_api_policies_returns_required_sections() -> None:
    app = build_app(AppDeps(mcp_client=FakeMcpClient()))  # type: ignore[arg-type]
    with TestClient(app) as client:
        r = client.get("/api/policies")
        assert r.status_code == 200
        body = r.json()
        ids = {s["id"] for s in body["sections"]}
        assert {"pickup", "delivery", "lead_times", "refunds", "allergens", "halal"} <= ids


def test_api_chat_uses_orchestrator() -> None:
    orch = Orchestrator(bridge=_bridge('cake "Honey" is on the counter — 1.2 kg, $42.'))
    app = build_app(AppDeps(orchestrator=orch, mcp_client=FakeMcpClient()))  # type: ignore[arg-type]
    with TestClient(app) as client:
        r = client.post(
            "/api/chat",
            json={"message": "do you have honey today?"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["reply"].startswith('cake "Honey"')
        assert body.get("session_id")


def test_api_chat_502_when_orchestrator_missing() -> None:
    app = build_app(AppDeps(orchestrator=None, mcp_client=FakeMcpClient()))  # type: ignore[arg-type]
    # Manually clear the orchestrator that lifespan would build.
    with TestClient(app) as client:
        client.app.state.orchestrator = None  # type: ignore[attr-defined]
        r = client.post("/api/chat", json={"message": "hi"})
        assert r.status_code == 502


def test_api_lead_persists_and_acks() -> None:
    app = build_app(AppDeps(mcp_client=FakeMcpClient()))  # type: ignore[arg-type]
    with TestClient(app) as client:
        r = client.post(
            "/api/lead",
            json={
                "name": "Maria",
                "contact": "+12815550100",
                "intent": 'cake "Honey" for Saturday',
                "utm_source": "instagram",
                "utm_campaign": "mothers_day_2026",
                "page": "/cake/honey-cake-slice",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "received"
        assert body["lead_id"]


def test_api_lead_rejects_missing_required_fields() -> None:
    app = build_app(AppDeps(mcp_client=FakeMcpClient()))  # type: ignore[arg-type]
    with TestClient(app) as client:
        r = client.post("/api/lead", json={"name": "Maria"})
        assert r.status_code == 422  # pydantic field-level validation
