#!/bin/bash
# Run Ralph with the claude-reddy license against this project.
# Usage: ./run-ralph.sh [max_iterations]
#   Default: 35 iterations (one per user story in prd.json)
#
# Open a separate terminal, cd to this directory, and run:
#   ./run-ralph.sh

set -e

export CLAUDE_CONFIG_DIR=/Users/gw/.claude-config-reddy

RALPH_DIR="$HOME/.claude/skills/ralph"

# Symlink prd.json and progress.txt into project dir so the agent
# finds them in CWD. Ralph.sh also accesses them at RALPH_DIR, and
# both paths resolve to the same file via symlink.
for f in prd.json progress.txt; do
  if [ ! -e "$f" ] && [ -f "$RALPH_DIR/$f" ]; then
    ln -s "$RALPH_DIR/$f" "$f"
  fi
done

MAX="${1:-35}"

exec "$RALPH_DIR/ralph.sh" --tool claude "$MAX"
