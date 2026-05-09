# Runtime persona — composed system prompt

This folder contains the system prompt for the **runtime Claude** — the customer-facing
assistant that answers messages on every channel (Telegram, WhatsApp, Instagram, the
website chat, the on-site widget). It is loaded at boot by `src/agents/system_prompt.py`,
concatenated in deterministic order, and passed to `claude -p` via `--system-prompt` by
`src/agents/claude_bridge.py`. The runtime model is pinned to `claude-opus-4-7` via the
`ANTHROPIC_MODEL` env var.

This folder is **not** for the developer ("Dev Claude") working on this repo. Developer
guidance lives in the root `CLAUDE.md` and in `docs/PLAN.md`.

## Files (composition order)

| Order | File | Job |
|---|---|---|
| 1 | `SOUL.md` | Identity, brand values, voice character. Who HappyCake is and how it speaks. |
| 2 | `RULES.md` | Hard + soft rules: wordmark, English-only, kitchen-capacity precondition, MCP-first, no fabrication, owner-approval flow, escalation triggers. |
| 3 | `TOOLS.md` | MCP tool catalog with when-to-use guidance. Sourced from `docs/mcp_inventory.md` after MCP recon. |
| 4 | `EXAMPLES.md` | Reference posts and reply templates that exemplify the brand voice. |

The composer joins them with clear separators so the runtime can refer to each section by
heading (`## SOUL`, `## RULES`, `## TOOLS`, `## EXAMPLES`). Edit any file in isolation;
the composer re-reads on every bot restart, no rebuild needed.

## Why this is split into four files

- **One file, one job.** Each section is owned by a different concern and can be updated
  without touching the others. Brand voice rarely changes; tools change every time the
  MCP inventory does.
- **Reviewable.** A diff on `RULES.md` shows exactly what behavior changed.
- **Composable.** A future workflow that needs a narrower persona (e.g. only marketing
  copy review) can compose a subset.

## Source of truth

Most content here is distilled from `HCU_BRANDBOOK.md` at the repo root. Where the
brandbook and these files conflict, **the brandbook wins** — open a PR to bring this
folder back in line.
