"""Shared pytest fixtures."""
from __future__ import annotations

import os
import pytest

# Headless Qt for all tests
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def server_url() -> str:
    return "http://abs.test:13378"


@pytest.fixture
def auth_token() -> str:
    return "test-token-abc123"
