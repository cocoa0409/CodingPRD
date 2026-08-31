"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.  Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def hub_admin_headers():
    return TEST_USERS["hub_admin_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["approver_headers"]


@pytest.fixture
def claims_officer_headers():
    return TEST_USERS["claims_officer_headers"]


@pytest.fixture
def board_director_headers():
    return TEST_USERS["board_director_headers"]


@pytest.fixture
def producer_headers():
    return TEST_USERS["producer_headers"]


@pytest.fixture
def buyer_headers():
    return TEST_USERS["buyer_headers"]
