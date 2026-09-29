"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def compliance_admin_headers():
    return TEST_USERS["compliance_admin_headers"]


@pytest.fixture
def brand_admin_headers():
    return TEST_USERS["brand_admin_headers"]


@pytest.fixture
def labeling_specialist_headers():
    return TEST_USERS["labeling_specialist_headers"]


@pytest.fixture
def labeling_approver_headers():
    return TEST_USERS["labeling_approver_headers"]


@pytest.fixture
def accredited_lab_headers():
    return TEST_USERS["accredited_lab_headers"]


@pytest.fixture
def customs_officer_headers():
    return TEST_USERS["customs_officer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
