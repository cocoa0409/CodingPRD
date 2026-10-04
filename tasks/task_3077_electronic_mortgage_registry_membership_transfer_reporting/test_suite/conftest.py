"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def registry_admin_headers():
    return TEST_USERS["registry_admin_headers"]


@pytest.fixture
def qa_creator_headers():
    return TEST_USERS["qa_creator_headers"]


@pytest.fixture
def qa_settler_headers():
    return TEST_USERS["qa_settler_headers"]


@pytest.fixture
def qa_judge_headers():
    return TEST_USERS["qa_judge_headers"]


@pytest.fixture
def borrower_inquirer_headers():
    return TEST_USERS["borrower_inquirer_headers"]


@pytest.fixture
def member_rep_headers():
    """Unbound fallback only. Member-scoped calls must build headers per member."""
    return TEST_USERS["member_rep_headers"]
