"""Pytest fixtures exposing the closeout-stores test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def buyer_headers():
    return TEST_USERS["sourcing_buyer_headers"]


@pytest.fixture
def buyer_alt_headers():
    return TEST_USERS["sourcing_buyer_alt_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def officer_alt_headers():
    return TEST_USERS["safety_officer_alt_headers"]


@pytest.fixture
def pricing_headers():
    return TEST_USERS["pricing_lead_headers"]


@pytest.fixture
def allocator_headers():
    return TEST_USERS["allocation_manager_headers"]


@pytest.fixture
def floor_headers():
    return TEST_USERS["store_manager_headers"]


@pytest.fixture
def guest_headers():
    return TEST_USERS["anonymous_headers"]
