#!/bin/bash
# Run Ralph with the claude-reddy license against this project.
# Usage: ./run-ralph.sh [max_iterations]
#   Default: 35 iterations (one per user story in prd.json)
#
# Open a separate terminal, cd to this directory, and run:
#   ./run-ralph.sh

set -e

export CLAUDE_CONFIG_DIR=/Users/gw/.claude-config-reddy

MAX="${1:-35}"

exec ~/.claude/skills/ralph/ralph.sh --tool claude "$MAX"
