"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def trade_designer_headers():
    return TEST_USERS["trade_designer_headers"]


@pytest.fixture
def gallery_associate_headers():
    return TEST_USERS["gallery_associate_headers"]


@pytest.fixture
def trade_reviewer_headers():
    return TEST_USERS["trade_reviewer_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def hub_operator_headers():
    return TEST_USERS["hub_operator_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
