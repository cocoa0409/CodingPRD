"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def house_manager_headers():
    return TEST_USERS["house_manager_headers"]


@pytest.fixture
def company_rep_headers():
    return TEST_USERS["company_rep_headers"]


@pytest.fixture
def box_office_agent_headers():
    return TEST_USERS["box_office_agent_headers"]
