"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import (
    BILLING_CLERK,
    DISPATCHER,
    LIFT_DIRECTOR,
    SAFETY_MANAGER,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the harness."""
    return api_client


@pytest.fixture
def dispatcher_headers():
    return DISPATCHER


@pytest.fixture
def lift_director_headers():
    return LIFT_DIRECTOR


@pytest.fixture
def safety_manager_headers():
    return SAFETY_MANAGER


@pytest.fixture
def billing_clerk_headers():
    return BILLING_CLERK


@pytest.fixture
def engineer_headers():
    return TEST_USERS["engineer_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
