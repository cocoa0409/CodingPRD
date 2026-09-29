"""Shared pytest fixtures for the zoological transfer compliance suite."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the API under test.

    The harness restarts the server with an empty database before every test, so
    every test builds the state it needs from scratch through the published
    endpoints.
    """
    return ApiClient()
