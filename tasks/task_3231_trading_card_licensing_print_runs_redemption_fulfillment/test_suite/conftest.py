"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's business."""
    return api_client


@pytest.fixture
def licensing_manager_headers():
    return TEST_USERS["licensing_manager_headers"]


@pytest.fixture
def product_manager_headers():
    return TEST_USERS["product_manager_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def signing_coordinator_headers():
    return TEST_USERS["signing_coordinator_headers"]


@pytest.fixture
def authentication_officer_headers():
    return TEST_USERS["authentication_officer_headers"]


@pytest.fixture
def redemption_analyst_headers():
    return TEST_USERS["redemption_analyst_headers"]


@pytest.fixture
def distribution_manager_headers():
    return TEST_USERS["distribution_manager_headers"]


@pytest.fixture
def quality_analyst_headers():
    return TEST_USERS["quality_analyst_headers"]


@pytest.fixture
def collector_support_headers():
    return TEST_USERS["collector_support_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]