"""End-to-end FastAPI tests via Starlette TestClient."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from src.core.config import get_settings
from src.webhooks.app import build_app
from src.webhooks.security import compute_signature


@pytest.fixture
def client(tmp_path: object) -> Iterator[TestClient]:
    os.environ["META_VERIFY_TOKEN"] = "v_token"
    os.environ["META_APP_SECRET"] = "s_secret"
    os.environ["SQLITE_PATH"] = str(tmp_path / "test.db")  # type: ignore[operator]
    get_settings.cache_clear()
    with TestClient(build_app()) as c:
        yield c
    for k in ("META_VERIFY_TOKEN", "META_APP_SECRET", "SQLITE_PATH"):
        os.environ.pop(k, None)
    get_settings.cache_clear()


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_unknown_channel_404(client: TestClient) -> None:
    r = client.get("/webhook/sms?hub.mode=subscribe&hub.verify_token=v_token&hub.challenge=x")
    assert r.status_code == 404


def test_verify_challenge_succeeds(client: TestClient) -> None:
    r = client.get(
        "/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=v_token&hub.challenge=42"
    )
    assert r.status_code == 200
    assert r.text == "42"


def test_verify_challenge_rejects_wrong_token(client: TestClient) -> None:
    r = client.get("/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=42")
    assert r.status_code == 403


def test_inbound_rejects_bad_signature(client: TestClient) -> None:
    r = client.post(
        "/webhook/whatsapp",
        content=b'{"x":1}',
        headers={"X-Hub-Signature-256": "sha256=deadbeef"},
    )
    assert r.status_code == 401


def test_inbound_accepts_valid_signature(client: TestClient) -> None:
    body = b'{"object":"whatsapp_business_account","entry":[]}'
    sig = compute_signature("s_secret", body)
    r = client.post(
        "/webhook/whatsapp",
        content=body,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "received"
