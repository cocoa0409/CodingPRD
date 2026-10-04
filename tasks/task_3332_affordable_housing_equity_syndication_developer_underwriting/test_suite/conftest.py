"""Pytest fixtures exposing the test_helpers infrastructure.

The runner starts a fresh API server before every test, so nothing here is
session-scoped beyond the stateless HTTP client: each test builds its own
entities through the public API.
"""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def developer_headers():
    return TEST_USERS["developer_headers"]


@pytest.fixture
def investor_headers():
    return TEST_USERS["investor_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def asset_manager_headers():
    return TEST_USERS["asset_manager_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def no_role_headers():
    """Headers carrying no X-User-Role at all — the 401 path."""
    from test_helpers import NO_ROLE_HEADERS

    return dict(NO_ROLE_HEADERS)
