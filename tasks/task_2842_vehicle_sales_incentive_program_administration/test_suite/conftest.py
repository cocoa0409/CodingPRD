"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# --- One fixture per role -----------------------------------------------------


@pytest.fixture
def program_designer_headers():
    return TEST_USERS["program_designer_headers"]


@pytest.fixture
def program_designer_2_headers():
    """A second ProgramDesigner principal, for segregation-of-duties scenarios."""
    return TEST_USERS["program_designer_2_headers"]


@pytest.fixture
def incentive_controller_headers():
    return TEST_USERS["incentive_controller_headers"]


@pytest.fixture
def incentive_controller_2_headers():
    """A second IncentiveController principal."""
    return TEST_USERS["incentive_controller_2_headers"]


@pytest.fixture
def field_sales_manager_headers():
    return TEST_USERS["field_sales_manager_headers"]


@pytest.fixture
def field_sales_manager_2_headers():
    return TEST_USERS["field_sales_manager_2_headers"]


@pytest.fixture
def claims_auditor_headers():
    """The anchor auditor identity used to validate deliveries."""
    return TEST_USERS["claims_auditor_headers"]


@pytest.fixture
def claims_auditor_2_headers():
    """A second auditor identity, used to adjudicate claims built on deliveries
    the first auditor validated."""
    return TEST_USERS["claims_auditor_2_headers"]


@pytest.fixture
def claims_auditor_3_headers():
    return TEST_USERS["claims_auditor_3_headers"]


@pytest.fixture
def dealer_headers():
    """A Dealer header whose X-User-ID matches no Dealer row. Use only where the
    test does not depend on the caller owning the subject resource; ownership
    tests build their headers with make_dealer_headers(dealer_id)."""
    return TEST_USERS["dealer_headers"]
