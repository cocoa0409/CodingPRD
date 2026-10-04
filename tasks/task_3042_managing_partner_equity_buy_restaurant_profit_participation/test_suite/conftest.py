"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def hr_recruiter_headers():
    return TEST_USERS["hr_recruiter_headers"]


@pytest.fixture
def corporate_controller_headers():
    return TEST_USERS["corporate_controller_headers"]


@pytest.fixture
def operations_auditor_headers():
    return TEST_USERS["operations_auditor_headers"]


@pytest.fixture
def managing_partner_headers():
    return TEST_USERS["managing_partner_headers"]


@pytest.fixture
def market_partner_headers():
    return TEST_USERS["market_partner_headers"]
