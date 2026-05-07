"""Idempotency-key generation and tracking helpers.

Mutating tool calls accept an `idempotency_key`. If a key has been seen before
(within the configured TTL), the cached prior result is returned instead of
re-executing. Keys are scoped per (workflow_id, tool_name) to avoid collisions.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def derive_key(scope: str, payload: dict[str, Any]) -> str:
    """Stable key from a JSON-serializable payload.

    Used when the caller doesn't supply an explicit idempotency_key. The hash
    is stable across runs as long as the payload's JSON form is stable.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{scope}:{canonical}".encode()).hexdigest()
    return digest[:32]
