"""Meta webhook signature verification (HMAC-SHA256).

Meta sends a header `X-Hub-Signature-256: sha256=<hex>` over the raw POST body.
We compute the same hash with our app secret and constant-time compare.
"""

from __future__ import annotations

import hashlib
import hmac

SIG_PREFIX = "sha256="


def compute_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"{SIG_PREFIX}{digest}"


def verify_signature(secret: str, body: bytes, header_value: str | None) -> bool:
    if not header_value or not header_value.startswith(SIG_PREFIX):
        return False
    expected = compute_signature(secret, body)
    return hmac.compare_digest(expected, header_value)
