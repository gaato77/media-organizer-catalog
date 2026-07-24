from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "schema" / "catalog-schema-v1.sql"
