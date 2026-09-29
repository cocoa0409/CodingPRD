"""Shared pytest fixtures for the studio operations compliance suite.

The service is relaunched against a freshly wiped database before each test, so
every test builds the state it needs from scratch and no test may rely on rows
another test created. The logical clock therefore also starts each test at the
service default of 2026-08-01T00:00:00Z.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: F401,E402  registers the status map
from test_helpers.api_client import StudioApiClient  # noqa: E402


@pytest.fixture
def client() -> StudioApiClient:
    """A client pointed at the service under test."""
    return StudioApiClient()
