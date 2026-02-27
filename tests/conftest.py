"""Shared test fixtures."""

from __future__ import annotations

import pytest

from merovingian.core.store import MerovingianStore


@pytest.fixture
def store(tmp_path):
    """Basic store backed by a temporary database."""
    db_path = tmp_path / "test.db"
    with MerovingianStore(db_path) as s:
        yield s
