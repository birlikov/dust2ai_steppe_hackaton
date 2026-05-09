# Owner-runtime persona — composed system prompt

This folder is the system prompt for the **owner-facing Claude** — the
operations assistant on the Telegram bot. The customer-facing persona lives
under `agent/`; the two are independent and cached separately.

The owner persona is loaded by `src/agents/system_prompt.py::load_owner_system_prompt()`
and passed to `claude -p --system-prompt …` via
`src/agents/claude_bridge.py::build_owner_bridge()`. The runtime model is
pinned to `claude-opus-4-7`.

## Why two personas

The customer persona greets friends, recommends cakes, and never reveals
internal numbers. The owner persona summarises sales, surfaces what needs
attention, and is allowed to discuss revenue, kitchen capacity, campaign
performance — **never to a customer**, only to the owner. The two roles
have different rules, different tools to prefer, different writing
conventions. Splitting them keeps each prompt small and reviewable.

## Files (composition order)

| Order | File | Job |
|---|---|---|
| 1 | `SOUL.md` | Identity. Who the ops assistant is, how it speaks. |
| 2 | `RULES.md` | Hard + soft rules: no JSON, brevity, English numbers, ask before mutating, escalate uncertainty. |
| 3 | `TOOLS.md` | MCP catalog reframed for ops use. Read tools always allowed; mutating channel tools route through the drafts approval queue. |
| 4 | `EXAMPLES.md` | Sample owner Q&A. |

The composer reads them in that order and joins with `## SOUL`, `## RULES`,
etc. headings so the runtime model can refer to each section by name.

## Source of truth

- Brand voice (when relevant): `HCU_BRANDBOOK.md`
- MCP tool catalog: `docs/mcp_inventory.md`
- Operational rules ("never delete a comment", "owner approves posts"):
  `HCU_BRANDBOOK.md` §7

Where this folder and the brandbook conflict, the brandbook wins.
