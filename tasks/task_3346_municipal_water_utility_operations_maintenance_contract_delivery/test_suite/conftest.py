"""Pytest fixtures exposing the shared test infrastructure.

The runner guarantees the API server is already listening at API_BASE_URL before
pytest starts and restarts it before every test, so every fixture here only
builds data through the public endpoints.
"""
import os
import sys

import pytest

# Allow `pytest <task_dir>/test_suite` to be run without an externally supplied
# PYTHONPATH: the task directory is the parent of this file's directory.
_TASK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_DIR not in sys.path:
    sys.path.insert(0, _TASK_DIR)

from test_helpers import api_client, ApiClient, TEST_USERS  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    make_employee_headers,
    make_municipality_admin_headers,
    make_operator_admin_headers,
    make_platform_admin_headers,
    missing_auth_headers,
    unknown_role_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def platform_admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def municipality_admin_headers() -> dict:
    return TEST_USERS["municipality_admin_headers"]


@pytest.fixture
def operator_admin_headers() -> dict:
    return TEST_USERS["operator_admin_headers"]


@pytest.fixture
def employee_headers() -> dict:
    return TEST_USERS["employee_headers"]


@pytest.fixture
def role_header_factory():
    """Build headers for a role, binding X-User-ID to a concrete entity id."""
    return {
        "platform_admin": make_platform_admin_headers,
        "municipality_admin": make_municipality_admin_headers,
        "operator_admin": make_operator_admin_headers,
        "employee": make_employee_headers,
        "missing": missing_auth_headers,
        "unknown_role": unknown_role_headers,
    }
