"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def planner_headers():
    return TEST_USERS["shop_planner_headers"]


@pytest.fixture
def quality_headers():
    return TEST_USERS["quality_manager_headers"]


@pytest.fixture
def machinist_headers():
    """Machinist headers naming no Operator - only for pre-operator probes."""
    return TEST_USERS["machinist_headers"]


@pytest.fixture
def inspector_headers():
    """Inspector headers naming no Operator - only for pre-operator probes."""
    return TEST_USERS["inspector_headers"]
