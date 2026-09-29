"""Shared pytest wiring for the Affiliate Program Management API suite.

The harness restarts the server before every test, so each test below starts
against an empty database with the logical clock at its §2.9 default of
`2026-08-01T00:00:00.000Z` until the test pins it.
"""

import os
import sys

import pytest

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

# Importing the error catalogue registers the §5 error_id → HTTP status map with
# the framework validators, so every validate_error call cross-checks the status.
from test_helpers import api_errors  # noqa: E402,F401
from test_helpers.api_client import AffiliateProgramApiClient  # noqa: E402


@pytest.fixture
def api() -> AffiliateProgramApiClient:
    """A client bound to the server under test."""
    return AffiliateProgramApiClient()
