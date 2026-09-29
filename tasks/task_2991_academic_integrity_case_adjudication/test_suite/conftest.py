"""Shared pytest fixtures.

The harness restarts the API server before every individual test, so the store
is empty at the start of each test function and the logical clock reads
`2026-08-01T00:00:00Z` (PRD §2.4).  Nothing here persists across tests.
"""
import os
import sys

import pytest

# The runner injects the task root on PYTHONPATH; this keeps a bare `pytest`
# invocation from the task root working too.
_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    make_dean_headers,
    make_officer_headers,
    make_registrar_headers,
)


@pytest.fixture
def api() -> ApiClient:
    """A fresh client bound to the runner-supplied `API_BASE_URL`."""
    return ApiClient()


@pytest.fixture
def officer():
    """IntegrityOfficer headers — the opaque office identity."""
    return make_officer_headers()


@pytest.fixture
def dean():
    """AppealsDean headers — the opaque dean identity."""
    return make_dean_headers()


@pytest.fixture
def registrar():
    """RegistrarOfficer headers — the opaque registrar identity."""
    return make_registrar_headers()
