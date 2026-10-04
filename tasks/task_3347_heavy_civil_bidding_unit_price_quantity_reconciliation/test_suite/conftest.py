"""Pytest fixtures exposing the test_helpers infrastructure.

The runner manages server lifecycle, ``API_BASE_URL`` and ``PYTHONPATH``; this
file only bridges the helper module into pytest fixtures.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client, make_surety_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's guarantee."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def estimator_headers():
    return TEST_USERS["estimator_headers"]


@pytest.fixture
def contracting_officer_headers():
    return TEST_USERS["contracting_officer_headers"]


@pytest.fixture
def project_manager_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def engineer_headers():
    return TEST_USERS["engineer_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def surety_headers_factory():
    """Build Surety headers bound to a concrete Surety id."""
    return make_surety_headers
