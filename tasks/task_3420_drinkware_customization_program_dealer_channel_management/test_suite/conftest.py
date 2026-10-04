"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle, API_BASE_URL injection, and PYTHONPATH;
tests import everything else directly from the test_helpers package.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def channel_manager_headers():
    return TEST_USERS["channel_manager_headers"]


@pytest.fixture
def channel_manager_admin_headers():
    return TEST_USERS["channel_manager_admin_headers"]


@pytest.fixture
def channel_manager_docs_headers():
    return TEST_USERS["channel_manager_docs_headers"]


@pytest.fixture
def field_inspector_headers():
    return TEST_USERS["field_inspector_headers"]


@pytest.fixture
def buyer_headers():
    return TEST_USERS["buyer_headers"]


@pytest.fixture
def prepress_tech_headers():
    return TEST_USERS["prepress_tech_headers"]


@pytest.fixture
def production_lead_headers():
    return TEST_USERS["production_lead_headers"]


@pytest.fixture
def warranty_agent_headers():
    return TEST_USERS["warranty_agent_headers"]


@pytest.fixture
def customer_care_headers():
    return TEST_USERS["customer_care_headers"]


@pytest.fixture
def dealer_headers():
    """Shared Dealer fallback — only for tests that do not exercise ownership."""
    return TEST_USERS["dealer_headers"]
