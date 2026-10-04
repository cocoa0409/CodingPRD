"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client, make_agency_producer_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def risk_consultant_headers():
    return TEST_USERS["risk_consultant_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def compliance_reporter_headers():
    return TEST_USERS["compliance_reporter_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def agency_producer_headers():
    """Fallback producer headers for calls that do not exercise ownership."""
    return TEST_USERS["agency_producer_headers"]


@pytest.fixture
def producer_for():
    """Build producer headers bound to a specific Agency id."""
    return make_agency_producer_headers