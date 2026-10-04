"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is owned by the runner: the API server is restarted before
every test, so each test starts against an empty database. The session-scoped
client below never health-checks or restarts anything.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client bound to API_BASE_URL."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def fed_liaison_headers():
    return TEST_USERS["fed_liaison_headers"]


@pytest.fixture
def procurement_officer_headers():
    return TEST_USERS["procurement_officer_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def quality_inspector_alt_headers():
    return TEST_USERS["quality_inspector_alt_headers"]


@pytest.fixture
def destruction_certifier_1_headers():
    return TEST_USERS["destruction_certifier_1_headers"]


@pytest.fixture
def destruction_certifier_2_headers():
    return TEST_USERS["destruction_certifier_2_headers"]


@pytest.fixture
def destruction_certifier_3_headers():
    return TEST_USERS["destruction_certifier_3_headers"]


@pytest.fixture
def destruction_certifier_4_headers():
    return TEST_USERS["destruction_certifier_4_headers"]


@pytest.fixture
def program_manager_headers():
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def program_manager_alt_headers():
    return TEST_USERS["program_manager_alt_headers"]


@pytest.fixture
def mint_director_headers():
    return TEST_USERS["mint_director_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def finance_officer_alt_headers():
    return TEST_USERS["finance_officer_alt_headers"]


@pytest.fixture
def collector_headers():
    """Shared Collector headers — non-ownership tests only. For any call that
    must own the resource, build per-instance headers with
    make_collector_headers(collector["id"]) instead."""
    return TEST_USERS["collector_headers"]


@pytest.fixture
def bullion_dealer_headers():
    """Shared BullionDealer headers — non-ownership tests only. For confirm,
    use make_bullion_dealer_headers(authorized_purchaser["id"])."""
    return TEST_USERS["bullion_dealer_headers"]
