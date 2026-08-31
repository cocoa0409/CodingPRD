"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def second_manager_headers():
    return TEST_USERS["second_manager_headers"]


@pytest.fixture
def teller_headers():
    return TEST_USERS["teller_headers"]


@pytest.fixture
def second_teller_headers():
    return TEST_USERS["second_teller_headers"]


@pytest.fixture
def carrier_headers():
    return TEST_USERS["carrier_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def fed_agent_headers():
    return TEST_USERS["fed_agent_headers"]
