"""Pytest fixtures exposing the test_helpers infrastructure.

The server lifecycle (and the empty database before every test) is owned by the
prd-bench local runner; these fixtures only hand tests the shared client and
the pre-built role headers.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def gpo_admin_headers():
    return TEST_USERS["gpo_admin_headers"]


@pytest.fixture
def gpo_admin_2_headers():
    return TEST_USERS["gpo_admin_2_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def analyst_2_headers():
    return TEST_USERS["analyst_2_headers"]


@pytest.fixture
def arbiter_headers():
    return TEST_USERS["arbiter_headers"]


@pytest.fixture
def arbiter_2_headers():
    return TEST_USERS["arbiter_2_headers"]


@pytest.fixture
def rep_headers():
    return TEST_USERS["rep_headers"]


@pytest.fixture
def rep_2_headers():
    return TEST_USERS["rep_2_headers"]


@pytest.fixture
def member_operator_headers():
    """Unbound fallback only: a MemberOperator's X-User-ID must be a member id."""
    return TEST_USERS["member_operator_headers"]


@pytest.fixture
def distributor_feed_headers():
    """Unbound fallback only: a DistributorFeed's X-User-ID is a distributor id."""
    return TEST_USERS["distributor_feed_headers"]
