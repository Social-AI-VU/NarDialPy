#!/usr/bin/env bash
# Install git hooks from scripts/hooks into the local .git/hooks directory
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOKS_DIR="$REPO_ROOT/scripts/hooks"
GIT_HOOKS_DIR="$REPO_ROOT/.git/hooks"

if [ ! -d "$GIT_HOOKS_DIR" ]; then
  echo "This does not look like a git repository (no .git/hooks). Run this from the repo root after git clone."
  exit 1
fi

echo "Installing git hooks from $HOOKS_DIR to $GIT_HOOKS_DIR"

for hook in "$HOOKS_DIR"/*; do
  if [ -f "$hook" ]; then
    hook_name=$(basename "$hook")
    target="$GIT_HOOKS_DIR/$hook_name"
    echo "Copying $hook_name -> $target"
    cp "$hook" "$target"
    chmod +x "$target"
  fi
done

echo "Hooks installed. To skip hooks on push use: git push --no-verify"
