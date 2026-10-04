"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns server lifecycle and injects API_BASE_URL; the session-scoped
``api`` fixture simply hands out the shared client singleton.  Role header
fixtures mirror TEST_USERS for tests that want fixture injection, but most
tests use the module-level constants and per-instance builders from
test_helpers directly (entity-backed roles need the real entity id).
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.  Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def awards_director_headers():
    return TEST_USERS["awards_director_headers"]


@pytest.fixture
def government_contact_headers():
    """Shared fallback — ownership-gated calls must use
    make_government_contact_headers(<government id>) instead."""
    return TEST_USERS["government_contact_headers"]


@pytest.fixture
def reviewer_headers():
    """Shared fallback — ownership-gated calls must use
    make_reviewer_headers(<profile id>) instead."""
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def committee_member_headers():
    """Shared fallback — committee calls must use
    make_committee_member_headers(<member id>) instead."""
    return TEST_USERS["committee_member_headers"]


@pytest.fixture
def member_headers():
    """Shared fallback — member-self calls must use
    make_member_headers(<member id>) instead."""
    return TEST_USERS["member_headers"]
