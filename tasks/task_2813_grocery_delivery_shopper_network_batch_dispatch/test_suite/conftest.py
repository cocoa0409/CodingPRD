"""Shared pytest configuration for the PRD compliance suite.

The runner relaunches the server and wipes the database before every
individual test, so each test starts against an empty system and must create
every row it depends on. Nothing is cached across tests.
"""

import os
import sys

import pytest

# test_helpers/ is a sibling of test_suite/ at the task root.
_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers import ApiClient  # noqa: E402
from test_helpers.test_users import ADMIN_HEADERS, SUPPORT_HEADERS  # noqa: E402


@pytest.fixture()
def api() -> ApiClient:
    """A fresh client per test, pointed at the freshly relaunched server."""
    return ApiClient()


@pytest.fixture()
def admin_headers():
    return ADMIN_HEADERS


@pytest.fixture()
def support_headers():
    return SUPPORT_HEADERS
