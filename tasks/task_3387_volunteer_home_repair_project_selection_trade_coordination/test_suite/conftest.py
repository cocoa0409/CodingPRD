"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns the server lifecycle and restarts the API server before every
individual test, so each test builds its own state from an empty database via
the helpers. Role-header fixtures mirror TEST_USERS; entity-backed roles
(Homeowner, Volunteer, TradePartner, SponsorRep) must instead use the
make_<role>_headers(entity_id) builders at the call site (PRD §2.1).
"""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def affiliate_staff_headers():
    return TEST_USERS["affiliate_staff_headers"]


@pytest.fixture
def assessor_headers():
    return TEST_USERS["assessor_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
