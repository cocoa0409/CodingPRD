"""Pytest fixtures exposing the driver-incentives test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def incentive_ops_headers():
    return TEST_USERS["incentive_ops_headers"]


@pytest.fixture
def payments_officer_headers():
    return TEST_USERS["payments_officer_headers"]


@pytest.fixture
def fraud_analyst_headers():
    return TEST_USERS["fraud_analyst_headers"]
