"""Shared pytest fixtures.

The harness restarts the API against an empty database before each test, so no
fixture here carries state between tests: they only hand out the client and the
identity headers each role needs.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API client under test."""
    return api_client


@pytest.fixture
def league_admin_headers() -> dict:
    return TEST_USERS["league_admin_headers"]


@pytest.fixture
def second_league_admin_headers() -> dict:
    return TEST_USERS["second_league_admin_headers"]


@pytest.fixture
def scout_headers() -> dict:
    return TEST_USERS["scout_headers"]


@pytest.fixture
def coaching_staff_headers() -> dict:
    return TEST_USERS["coaching_staff_headers"]


@pytest.fixture
def performance_support_headers() -> dict:
    return TEST_USERS["performance_support_headers"]


@pytest.fixture
def finance_officer_headers() -> dict:
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def second_finance_officer_headers() -> dict:
    return TEST_USERS["second_finance_officer_headers"]


@pytest.fixture
def general_manager_headers() -> dict:
    """Not ownership-scoped: use make_general_manager_headers(org_id) for that."""
    return TEST_USERS["general_manager_headers"]


@pytest.fixture
def sponsorship_manager_headers() -> dict:
    return TEST_USERS["sponsorship_manager_headers"]


@pytest.fixture
def ops_manager_headers() -> dict:
    return TEST_USERS["ops_manager_headers"]


@pytest.fixture
def player_agent_headers() -> dict:
    return TEST_USERS["player_agent_headers"]


@pytest.fixture
def guardian_representative_headers() -> dict:
    return TEST_USERS["guardian_representative_headers"]
