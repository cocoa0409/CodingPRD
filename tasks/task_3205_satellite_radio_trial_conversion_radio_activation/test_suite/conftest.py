"""Pytest fixtures bridging test_helpers into the suite."""

import pytest

from test_helpers import ApiClient, fixtures
from test_helpers.test_users import (
    ANONYMOUS_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    RETENTION_AGENT_HEADERS,
    SYSTEM_OPERATOR_HEADERS,
)


@pytest.fixture()
def api() -> ApiClient:
    """Client aimed at the server under test; the runner injects API_BASE_URL."""
    return ApiClient()


@pytest.fixture()
def admin_headers():
    return PLATFORM_ADMIN_HEADERS


@pytest.fixture()
def retention_headers():
    return RETENTION_AGENT_HEADERS


@pytest.fixture()
def sysop_headers():
    return SYSTEM_OPERATOR_HEADERS


@pytest.fixture()
def anonymous_headers():
    return ANONYMOUS_HEADERS
