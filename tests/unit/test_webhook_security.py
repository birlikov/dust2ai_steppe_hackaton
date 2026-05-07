"""Tests for Meta webhook HMAC signature verification."""

from __future__ import annotations

from src.webhooks.security import compute_signature, verify_signature


def test_compute_signature_is_deterministic() -> None:
    a = compute_signature("secret", b"hello")
    b = compute_signature("secret", b"hello")
    assert a == b
    assert a.startswith("sha256=")


def test_verify_accepts_correct_signature() -> None:
    secret = "abc"
    body = b'{"x":1}'
    sig = compute_signature(secret, body)
    assert verify_signature(secret, body, sig) is True


def test_verify_rejects_wrong_signature() -> None:
    secret = "abc"
    body = b'{"x":1}'
    assert verify_signature(secret, body, "sha256=deadbeef") is False


def test_verify_rejects_missing_or_malformed_header() -> None:
    assert verify_signature("s", b"x", None) is False
    assert verify_signature("s", b"x", "") is False
    assert verify_signature("s", b"x", "sha1=foo") is False
