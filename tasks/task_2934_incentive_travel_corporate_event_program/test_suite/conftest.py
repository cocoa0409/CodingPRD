"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_director_headers():
    return TEST_USERS["program_director_headers"]


@pytest.fixture
def sourcing_manager_headers():
    return TEST_USERS["sourcing_manager_headers"]


@pytest.fixture
def sourcing_manager_alt_headers():
    return TEST_USERS["sourcing_manager_alt_headers"]


@pytest.fixture
def contract_approver_headers():
    return TEST_USERS["contract_approver_headers"]


@pytest.fixture
def contract_approver_alt_headers():
    return TEST_USERS["contract_approver_alt_headers"]


@pytest.fixture
def sales_ops_analyst_headers():
    return TEST_USERS["sales_ops_analyst_headers"]


@pytest.fixture
def travel_desk_headers():
    return TEST_USERS["travel_desk_headers"]


@pytest.fixture
def tax_officer_headers():
    return TEST_USERS["tax_officer_headers"]


@pytest.fixture
def tax_officer_alt_headers():
    return TEST_USERS["tax_officer_alt_headers"]


@pytest.fixture
def participant_headers():
    """Participant is entity_backed on Qualifier: ownership-gated calls must use
    `make_participant_headers(qualifier_id)` instead of this fallback."""
    return TEST_USERS["participant_headers"]
