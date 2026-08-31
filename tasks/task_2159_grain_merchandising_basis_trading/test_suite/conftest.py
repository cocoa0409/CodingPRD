"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def desk_admin_headers():
    return TEST_USERS["desk_admin_headers"]


@pytest.fixture
def merchandiser_headers():
    return TEST_USERS["merchandiser_headers"]


@pytest.fixture
def futures_trader_headers():
    return TEST_USERS["futures_trader_headers"]


@pytest.fixture
def risk_officer_headers():
    return TEST_USERS["risk_officer_headers"]


@pytest.fixture
def grain_inspector_headers():
    return TEST_USERS["grain_inspector_headers"]


@pytest.fixture
def freight_coordinator_headers():
    return TEST_USERS["freight_coordinator_headers"]
