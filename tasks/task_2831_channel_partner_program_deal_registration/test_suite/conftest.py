"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.  Server lifecycle is managed by the test runner."""
    return api_client


@pytest.fixture
def partner_headers():
    return TEST_USERS["partner_headers"]


@pytest.fixture
def channel_ops_analyst_headers():
    return TEST_USERS["channel_ops_analyst_headers"]


@pytest.fixture
def channel_ops_analyst_2_headers():
    return TEST_USERS["channel_ops_analyst_2_headers"]


@pytest.fixture
def channel_director_headers():
    return TEST_USERS["channel_director_headers"]


@pytest.fixture
def channel_director_2_headers():
    return TEST_USERS["channel_director_2_headers"]


@pytest.fixture
def direct_sales_rep_headers():
    return TEST_USERS["direct_sales_rep_headers"]


@pytest.fixture
def direct_sales_rep_2_headers():
    return TEST_USERS["direct_sales_rep_2_headers"]
