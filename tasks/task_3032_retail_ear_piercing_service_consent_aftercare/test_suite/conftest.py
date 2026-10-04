"""Pytest fixtures exposing the generated test infrastructure.

The runner restarts the server before every individual test, so each test
starts against an empty database and builds its own preconditions.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client, make_customer_headers, make_piercer_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_associate_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["store_manager_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["sterilization_technician_headers"]


@pytest.fixture
def reader_headers():
    return TEST_USERS["any_authenticated_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def piercer_headers_factory():
    """Build Piercer-role headers bound to a specific Piercer row id."""
    return make_piercer_headers


@pytest.fixture
def customer_headers_factory():
    """Build Customer-role headers bound to a specific Customer row id."""
    return make_customer_headers