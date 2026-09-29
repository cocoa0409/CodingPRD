"""
Shared pytest fixtures for the Plant Breeding Variety Trials compliance suite.

The suite runs with a fresh server per test, so no test may lean on state left
behind by another one: every scenario is rebuilt through the API's own declared
endpoints by the helpers in ``test_helpers.fixtures``.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the server under test."""
    return ApiClient()
