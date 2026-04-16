"""Deterministic system-prompt composer.

Joins reusable prompt blocks (e.g., FIDELITY_STANDARD, INVARIANTS, etc. from
`fidelity.py`) into a single system prompt. Output is byte-identical for the
same inputs so prompt caching upstream stays stable.

Dynamic payload content (per-call user data) MUST NOT be passed here — put it
in the user message instead. Anything composed via this helper becomes part of
the cached system block.
"""

from __future__ import annotations

_BLOCK_SEPARATOR = "\n\n---\n\n"
_TASK_PREFIX = "\n\n## Task\n\n"


def compose_system_prompt(*blocks: str, task: str) -> str:
    """Join `blocks` with a stable separator and append `task`.

    Raises:
        ValueError: if `task` is empty or whitespace-only.
    """
    if not task or not task.strip():
        raise ValueError("task must be a non-empty, non-whitespace string")
    return _BLOCK_SEPARATOR.join(blocks) + _TASK_PREFIX + task
