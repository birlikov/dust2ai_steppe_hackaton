from __future__ import annotations

from src.core.config import get_settings
from src.core.errors import error, invalid_input, not_found, ok
from src.core.idempotency import derive_key


def test_settings_load_with_defaults() -> None:
    s = get_settings()
    assert s.anthropic_default_model == "claude-haiku-4-5"
    assert s.log_level in {"DEBUG", "INFO", "WARNING", "ERROR"}


def test_tool_result_helpers() -> None:
    assert ok({"x": 1})["status"] == "ok"
    assert not_found("missing")["status"] == "not_found"
    assert invalid_input("bad")["status"] == "invalid_input"
    assert error("boom")["status"] == "error"


def test_derive_key_is_stable_and_short() -> None:
    k1 = derive_key("tool:create_booking", {"a": 1, "b": [2, 3]})
    k2 = derive_key("tool:create_booking", {"b": [2, 3], "a": 1})  # reordered
    assert k1 == k2
    assert len(k1) == 32


def test_derive_key_changes_on_payload_change() -> None:
    a = derive_key("tool:x", {"v": 1})
    b = derive_key("tool:x", {"v": 2})
    assert a != b
