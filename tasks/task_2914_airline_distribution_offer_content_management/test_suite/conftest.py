"""Pytest fixtures exposing the test_helpers infrastructure.

The runner restarts the API server before every individual test, so each test
begins against an empty database with the logical clock back at its startup
value.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    DISTRIBUTION_MANAGER_HEADERS,
    OTHER_DISTRIBUTION_MANAGER_HEADERS,
    PRICING_ANALYST_HEADERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return ADMIN_HEADERS


@pytest.fixture
def analyst_headers():
    return PRICING_ANALYST_HEADERS


@pytest.fixture
def manager_headers():
    return DISTRIBUTION_MANAGER_HEADERS


@pytest.fixture
def other_manager_headers():
    return OTHER_DISTRIBUTION_MANAGER_HEADERS


@pytest.fixture
def auditor_headers():
    return AUDITOR_HEADERS
