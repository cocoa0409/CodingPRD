"""Shared pytest fixtures for the returns-processing compliance suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: E402,F401  (registers status map)
from test_helpers.api_client import ApiClient  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the server under test.

    The harness restarts the server before every test, so each test starts
    against an empty database and a logical clock reading its startup default
    of 2026-08-01T00:00:00Z.
    """
    return ApiClient()
