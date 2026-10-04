"""Pytest fixtures bridging the test_helpers package into the suite.

The server lifecycle is owned by the runner: every test starts against a
fresh process and an empty database, with the logical clock at its startup
default.  These fixtures only expose the shared API client and the prebuilt
role header sets.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the runner guarantees the server is up."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def account_manager_headers():
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def lab_procurement_headers():
    return TEST_USERS["lab_procurement_headers"]


@pytest.fixture
def service_dispatcher_headers():
    return TEST_USERS["service_dispatcher_headers"]


@pytest.fixture
def field_engineer_headers():
    return TEST_USERS["field_engineer_headers"]


@pytest.fixture
def supply_ops_headers():
    return TEST_USERS["supply_ops_headers"]
