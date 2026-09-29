"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import (
    ANALYST_ONE,
    ANALYST_TWO,
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client against the running server."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def regulator_analyst_headers():
    """The analyst who accepts an application into review — analyst-1."""
    return TEST_USERS["regulator_analyst_headers"]


@pytest.fixture
def regulator_analyst_two_headers():
    """A second analyst — analyst-2 — free to issue the decision."""
    return TEST_USERS["regulator_analyst_two_headers"]


@pytest.fixture
def escrow_officer_headers():
    return TEST_USERS["escrow_officer_headers"]


@pytest.fixture
def broker_headers():
    """Fallback Broker headers for calls that do not exercise ownership."""
    return TEST_USERS["broker_headers"]


@pytest.fixture
def buyer_headers():
    """Fallback Buyer headers for calls that do not exercise ownership."""
    return TEST_USERS["buyer_headers"]


@pytest.fixture
def seller_headers():
    """Fallback Seller headers for calls that do not exercise ownership."""
    return TEST_USERS["seller_headers"]


@pytest.fixture
def analyst_one_id():
    return ANALYST_ONE


@pytest.fixture
def analyst_two_id():
    return ANALYST_TWO
