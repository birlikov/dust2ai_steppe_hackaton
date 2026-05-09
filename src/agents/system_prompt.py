"""Compose the runtime Claude system prompt from agent/*.md.

The runtime persona is split across four files under `agent/` (SOUL, RULES, TOOLS,
EXAMPLES). This module reads them in deterministic order at import time, joins them
with section headings, and exposes the result via :func:`load_system_prompt`. The
result is cached for the lifetime of the process so a bot restart is required to pick
up edits — that is intentional (we want a stable persona per process).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.core.config import REPO_ROOT

AGENT_DIR: Path = REPO_ROOT / "agent"

# Order matters: SOUL first (identity), then RULES (constraints), then TOOLS
# (capabilities), then EXAMPLES (style anchors). Each section is wrapped in a
# clear heading so the runtime model can refer to it.
SECTION_ORDER: tuple[str, ...] = ("SOUL", "RULES", "TOOLS", "EXAMPLES")


class PersonaLoadError(RuntimeError):
    """Raised when one or more persona files are missing or unreadable."""


def _read_section(name: str) -> str:
    path = AGENT_DIR / f"{name}.md"
    if not path.exists():
        raise PersonaLoadError(f"persona section missing: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise PersonaLoadError(f"persona section empty: {path}")
    return text


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    """Return the composed runtime system prompt.

    Cached at module level — the first call on bot boot reads from disk, subsequent
    calls return the cached string. Invalidate by restarting the process.
    """
    parts: list[str] = []
    for section in SECTION_ORDER:
        body = _read_section(section)
        parts.append(f"## {section}\n\n{body}")
    return "\n\n---\n\n".join(parts)
