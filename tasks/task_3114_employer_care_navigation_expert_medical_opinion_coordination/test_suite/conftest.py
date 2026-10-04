"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def employer_admin_headers():
    return TEST_USERS["employer_admin_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def nurse_navigator_headers():
    return TEST_USERS["nurse_navigator_headers"]


@pytest.fixture
def care_advocate_headers():
    return TEST_USERS["care_advocate_headers"]


@pytest.fixture
def physician_advisor_headers():
    return TEST_USERS["physician_advisor_headers"]


@pytest.fixture
def records_specialist_headers():
    return TEST_USERS["records_specialist_headers"]


@pytest.fixture
def expert_reviewer_headers():
    return TEST_USERS["expert_reviewer_headers"]


@pytest.fixture
def billing_advocate_headers():
    return TEST_USERS["billing_advocate_headers"]


@pytest.fixture
def plan_administrator_headers():
    return TEST_USERS["plan_administrator_headers"]
