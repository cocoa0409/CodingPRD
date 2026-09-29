"""Shared pytest wiring for the Nitrogen Fertilizer Production suite.

The service is restarted before every individual test, so each test opens
against an empty store and builds its own preconditions through the declared
endpoints.
"""

import sys
from pathlib import Path

import pytest

_TASK_ROOT = Path(__file__).resolve().parent.parent
if str(_TASK_ROOT) not in sys.path:
    sys.path.insert(0, str(_TASK_ROOT))

from test_helpers.api_client import ApiClient  # noqa: E402


@pytest.fixture
def api():
    """A client bound to the service under test."""
    return ApiClient()
