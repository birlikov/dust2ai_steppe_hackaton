from __future__ import annotations

from pathlib import Path

import pytest
from src.core.config import get_settings
from src.storage import db, drafts


@pytest.fixture(autouse=True)
async def _isolate_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "drafts_test.db")
    await db.close()
    yield
    await db.close()


@pytest.mark.asyncio
async def test_create_pending_draft_round_trips() -> None:
    d = await drafts.create(
        channel="instagram",
        kind="post",
        payload={"caption": 'Cake "Honey" — 1.2 kg, $42.', "imageUrl": "/x.webp"},
    )
    assert d.status == "pending"
    assert d.payload["caption"].startswith("Cake")
    fetched = await drafts.get(d.id)
    assert fetched is not None
    assert fetched.payload == d.payload


@pytest.mark.asyncio
async def test_approve_transitions_status() -> None:
    d = await drafts.create(channel="instagram", kind="post", payload={"a": 1})
    out = await drafts.approve(d.id)
    assert out.status == "approved"


@pytest.mark.asyncio
async def test_edit_records_owner_text_and_requeues() -> None:
    d = await drafts.create(channel="instagram", kind="post", payload={"a": 1})
    out = await drafts.edit(d.id, "swap the photo for hero-02")
    assert out.status == "pending"
    assert out.edit_text == "swap the photo for hero-02"


@pytest.mark.asyncio
async def test_reject_records_reason() -> None:
    d = await drafts.create(channel="instagram", kind="post", payload={"a": 1})
    out = await drafts.reject(d.id, "off-brand voice; too breathless")
    assert out.status == "rejected"
    assert out.reject_reason and "off-brand" in out.reject_reason


@pytest.mark.asyncio
async def test_mark_published_records_external_id() -> None:
    d = await drafts.create(channel="instagram", kind="post", payload={"a": 1})
    await drafts.approve(d.id)
    out = await drafts.mark_published(d.id, external_id="ig_post_42")
    assert out.status == "published"
    assert out.external_id == "ig_post_42"


@pytest.mark.asyncio
async def test_list_status_filters_and_orders() -> None:
    a = await drafts.create(channel="instagram", kind="post", payload={"i": 1})
    b = await drafts.create(channel="google_business", kind="post", payload={"i": 2})
    await drafts.reject(b.id, "later")
    pending = await drafts.list_status("pending")
    assert [d.id for d in pending] == [a.id]
    rejected = await drafts.list_status("rejected")
    assert [d.id for d in rejected] == [b.id]


@pytest.mark.asyncio
async def test_list_status_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        await drafts.list_status("nope")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_owner_identity_round_trip() -> None:
    assert await drafts.get_owner() is None
    await drafts.remember_owner(chat_id=12345, username="askhat")
    rec = await drafts.get_owner()
    assert rec is not None
    assert rec.telegram_chat_id == 12345
    assert rec.telegram_username == "askhat"


@pytest.mark.asyncio
async def test_lead_round_trip_and_marker() -> None:
    lead = await drafts.insert_lead(
        name="Maria",
        contact="+12815550100",
        intent='cake "Honey" for Saturday',
        utm_source="instagram",
        utm_campaign="mothers_day_2026",
    )
    assert lead.utm_campaign == "mothers_day_2026"
    assert lead.reported_to_owner_at is None
    await drafts.mark_lead_reported(lead.id)
    leads = list(await drafts.list_recent_leads())
    assert leads[0].reported_to_owner_at is not None
