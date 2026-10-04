"""Shared pytest wiring for the Service Corps Placement suite.

The harness restarts the API server before each test, so every test starts
against an empty database (and the logical clock at its fixed initial reading
of 2026-09-01T00:00:00Z) and builds the world it needs through the public API
via the composite fixtures in test_helpers. The base URL is injected into the
environment by the runner, so the client is constructed with no arguments.
"""

import pytest

from test_helpers import (
    PROGRAM_MANAGER_HEADERS,
    SITE_DIRECTOR_HEADERS,
    STIPEND_ADMIN_1_HEADERS,
    STIPEND_ADMIN_2_HEADERS,
    ApiClient,
)


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test."""
    return ApiClient()


@pytest.fixture()
def site_director_headers() -> dict:
    return SITE_DIRECTOR_HEADERS


@pytest.fixture()
def program_manager_headers() -> dict:
    return PROGRAM_MANAGER_HEADERS


@pytest.fixture()
def stipend_admin_1_headers() -> dict:
    return STIPEND_ADMIN_1_HEADERS


@pytest.fixture()
def stipend_admin_2_headers() -> dict:
    return STIPEND_ADMIN_2_HEADERS
