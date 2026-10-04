"""Pytest fixtures exposing test_helpers infrastructure."""
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
def coverage_reviewer_headers():
    return TEST_USERS["coverage_reviewer_headers"]


@pytest.fixture
def fulfillment_agent_headers():
    return TEST_USERS["fulfillment_agent_headers"]


@pytest.fixture
def billing_agent_headers():
    return TEST_USERS["billing_agent_headers"]


@pytest.fixture
def warranty_reviewer_headers():
    return TEST_USERS["warranty_reviewer_headers"]


@pytest.fixture
def quality_engineer_headers():
    return TEST_USERS["quality_engineer_headers"]


@pytest.fixture
def patient_support_agent_headers():
    return TEST_USERS["patient_support_agent_headers"]


@pytest.fixture
def prescriber_headers():
    return TEST_USERS["prescriber_headers"]


@pytest.fixture
def patient_headers():
    return TEST_USERS["patient_headers"]
