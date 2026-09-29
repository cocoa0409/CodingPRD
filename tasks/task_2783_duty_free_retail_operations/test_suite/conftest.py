"""Shared pytest wiring for the Duty-Free Retail Operations compliance suite.

The API server is restarted before every test, so each test starts against an
empty database with the logical clock at its boot value of 2026-08-01T00:00:00Z
and builds every precondition it needs through declared endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import DutyFreeApiClient  # noqa: E402


@pytest.fixture()
def api() -> DutyFreeApiClient:
    """An HTTP client bound to the API under test."""
    return DutyFreeApiClient()
