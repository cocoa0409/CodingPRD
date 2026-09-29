"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def developer_principal_headers():
    return TEST_USERS["developer_principal_headers"]


@pytest.fixture
def entitlement_officer_headers():
    return TEST_USERS["entitlement_officer_headers"]


@pytest.fixture
def construction_manager_headers():
    return TEST_USERS["construction_manager_headers"]


@pytest.fixture
def leasing_agent_headers():
    return TEST_USERS["leasing_agent_headers"]


@pytest.fixture
def asset_manager_headers():
    return TEST_USERS["asset_manager_headers"]


@pytest.fixture
def property_manager_headers():
    return TEST_USERS["property_manager_headers"]


@pytest.fixture
def household_headers():
    """Shared Household constant — only for tests that do not exercise ownership.
    Ownership-gated calls must use make_household_headers(household["id"])."""
    return TEST_USERS["household_headers"]
