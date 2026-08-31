"""Pytest fixtures exposing the generated test_helpers infrastructure."""

import pytest

from test_helpers import (
    ANONYMOUS_HEADERS,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def accountant_headers():
    return TEST_USERS["accountant_headers"]


@pytest.fixture
def billing_agent_headers():
    return TEST_USERS["billing_agent_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS
