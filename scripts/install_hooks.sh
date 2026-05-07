#!/usr/bin/env bash
# Install the pre-commit hook into .git/hooks/. Idempotent.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOK_PATH="$REPO_ROOT/.git/hooks/pre-commit"

cat > "$HOOK_PATH" <<'EOF'
#!/usr/bin/env bash
# Block pushes that would fail lint, types, or unit tests.
# Skip with `git commit --no-verify` only if you know what you're doing.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "→ ruff"
uv run ruff check src tests
echo "→ mypy"
uv run mypy src
echo "→ pytest (unit only, --timeout=30)"
uv run pytest -q tests/unit --timeout=30 2>/dev/null || \
  uv run pytest -q tests/unit
echo "✓ pre-commit ok"
EOF

chmod +x "$HOOK_PATH"
echo "Installed pre-commit hook at $HOOK_PATH"
