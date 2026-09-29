"""Shared pytest wiring for the API compliance suite.

The server under test is restarted with an empty database before every
individual test, so no fixture here may assume any pre-existing row; every test
builds the state it needs through real API calls.
"""

import os
import sys

import pytest

# Make the sibling test_helpers package importable when pytest is invoked from
# either the task root or the test_suite directory.
_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers import api_errors  # noqa: E402,F401  (registers the error status map)


@pytest.fixture
def api() -> ApiClient:
    """A fresh client bound to the service under test."""
    return ApiClient()
