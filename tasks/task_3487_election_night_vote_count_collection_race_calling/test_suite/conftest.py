"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH: the API under test is
already reachable at API_BASE_URL, and test_helpers is importable. Fixtures
here are a thin bridge; per-instance role headers come from the
make_<role>_headers builders in test_helpers.test_users (mandatory for the
entity-backed Stringer and MediaCustomer roles).
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def planner_headers():
    return TEST_USERS["planner_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def feed_operator_headers():
    return TEST_USERS["feed_operator_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def analyst_kim_headers():
    return TEST_USERS["analyst_kim_headers"]


@pytest.fixture
def chief_headers():
    return TEST_USERS["chief_headers"]


@pytest.fixture
def recount_officer_headers():
    return TEST_USERS["recount_officer_headers"]


@pytest.fixture
def stringer_headers():
    """FALLBACK Stringer headers (fixed non-entity id): only for tests whose
    outcome does not depend on owning a resource. For check-in, STRINGER
    reports, and own-report resubmits use make_stringer_headers(entity_id)."""
    return TEST_USERS["stringer_headers"]


@pytest.fixture
def customer_headers():
    """FALLBACK MediaCustomer headers: only for non-ownership tests. For
    self-reads, delivery feeds, and invoices use
    make_customer_headers(customer_id)."""
    return TEST_USERS["customer_headers"]
