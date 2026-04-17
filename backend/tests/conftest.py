"""Shared pytest fixtures.

Clears the cached Settings instance between tests so ``monkeypatch.setenv``
changes take effect. ``phase_artifacts._settings`` is ``lru_cache``-d to
avoid re-parsing the env file on every artifact read — but that cache
would otherwise leak between tests.
"""

from __future__ import annotations

import pytest

from walkthrough.storage import phase_artifacts


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    phase_artifacts._settings.cache_clear()
