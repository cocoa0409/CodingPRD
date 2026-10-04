"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_ops_headers():
    return TEST_USERS["platform_ops_headers"]


@pytest.fixture
def programming_manager_headers():
    return TEST_USERS["programming_manager_headers"]


@pytest.fixture
def finance_ops_headers():
    return TEST_USERS["finance_ops_headers"]


@pytest.fixture
def content_officer_headers():
    return TEST_USERS["content_officer_headers"]


@pytest.fixture
def distributor_headers():
    return TEST_USERS["distributor_headers"]


@pytest.fixture
def exhibitor_headers():
    return TEST_USERS["exhibitor_headers"]


@pytest.fixture
def theater_headers():
    return TEST_USERS["theater_headers"]