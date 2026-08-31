"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def second_case_manager_headers():
    return TEST_USERS["second_case_manager_headers"]


@pytest.fixture
def utilization_review_nurse_headers():
    return TEST_USERS["utilization_review_nurse_headers"]


@pytest.fixture
def second_utilization_review_nurse_headers():
    return TEST_USERS["second_utilization_review_nurse_headers"]


@pytest.fixture
def discharge_coordinator_headers():
    return TEST_USERS["discharge_coordinator_headers"]


@pytest.fixture
def second_discharge_coordinator_headers():
    return TEST_USERS["second_discharge_coordinator_headers"]


@pytest.fixture
def payer_representative_headers():
    """Shared PayerRepresentative constant — only for calls that never reach the
    payer ownership check."""
    return TEST_USERS["payer_representative_headers"]


@pytest.fixture
def post_acute_liaison_headers():
    """Shared PostAcuteLiaison constant — only for calls that never reach the
    provider ownership check."""
    return TEST_USERS["post_acute_liaison_headers"]
