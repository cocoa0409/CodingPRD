"""Pytest configuration for the Public Records Data Journalism Desk suite.

The server lifecycle, the base URL and result collection are owned by the
runner. This module only puts the task root on ``sys.path`` so ``test_helpers``
imports resolve, and exposes the single ``api`` fixture every test uses.

The harness restarts the server before each individual test, so every test
starts against an empty database and builds its own preconditions through the
endpoints of PRD S4. Importing ``test_helpers.api_errors`` here registers the
PRD S5 error -> HTTP status map with the framework validators once per session.
"""

import os
import sys

import pytest

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers import api_errors  # noqa: E402,F401
from test_helpers.api_client import ApiClient  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the base URL the runner exports as ``API_BASE_URL``."""
    return ApiClient()
