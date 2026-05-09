"""Compose runtime system prompts from a persona directory.

We have **two** runtime personas. Each lives in its own folder, four small
files (SOUL, RULES, TOOLS, EXAMPLES) composed in deterministic order:

  - ``agent/`` — customer-facing assistant (replies on the website chat,
    WhatsApp, Instagram). Loaded via :func:`load_system_prompt`.
  - ``owner_agent/`` — operations assistant for the business owner on
    Telegram. Loaded via :func:`load_owner_system_prompt`.

Each loader is cached separately (``maxsize=1``) so a bot restart is
required to pick up persona edits — that is intentional, we want a stable
persona per process.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.core.config import REPO_ROOT

AGENT_DIR: Path = REPO_ROOT / "agent"
OWNER_AGENT_DIR: Path = REPO_ROOT / "owner_agent"

# Order matters: SOUL first (identity), then RULES (constraints), then TOOLS
# (capabilities), then EXAMPLES (style anchors). Each section is wrapped in a
# clear heading so the runtime model can refer to it.
SECTION_ORDER: tuple[str, ...] = ("SOUL", "RULES", "TOOLS", "EXAMPLES")


class PersonaLoadError(RuntimeError):
    """Raised when one or more persona files are missing or unreadable."""


def _read_section(persona_dir: Path, name: str) -> str:
    path = persona_dir / f"{name}.md"
    if not path.exists():
        raise PersonaLoadError(f"persona section missing: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise PersonaLoadError(f"persona section empty: {path}")
    return text


def _compose(persona_dir: Path) -> str:
    parts: list[str] = []
    for section in SECTION_ORDER:
        body = _read_section(persona_dir, section)
        parts.append(f"## {section}\n\n{body}")
    return "\n\n---\n\n".join(parts)


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    """Return the composed customer-facing runtime system prompt.

    Cached at module level — the first call on bot boot reads from disk,
    subsequent calls return the cached string. Invalidate by restarting the
    process.
    """
    return _compose(AGENT_DIR)


@lru_cache(maxsize=1)
def load_owner_system_prompt() -> str:
    """Return the composed owner-facing operations-assistant prompt.

    Same caching semantics as :func:`load_system_prompt`. Use with
    :func:`src.agents.claude_bridge.build_owner_bridge`.
    """
    return _compose(OWNER_AGENT_DIR)
