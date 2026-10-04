"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns the server lifecycle and PYTHONPATH; these fixtures only
bridge names.  The server is restarted before every test, so each test
starts against an empty database with the logical clock at exactly
2026-09-01T00:00:00Z (PRD section 2.4) — fixtures build every precondition
from scratch through the public API.

Entity-backed roles (Issuer, Underwriter) intentionally have NO shared
header fixture: their headers must be built from the created record via
``make_issuer_headers(issuer["id"])`` / ``make_underwriter_headers(...)``.
The placeholder constants in TEST_USERS exist only for tests that never
exercise an ownership check.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_2_HEADERS,
    ANALYST_HEADERS,
    CHAIR_2_HEADERS,
    CHAIR_HEADERS,
    OFFICER_HEADERS,
    ApiClient,
    api_client,
    make_committee_member_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server lifecycle is the runner's."""
    return api_client


@pytest.fixture
def admin_headers():
    return ADMIN_HEADERS


@pytest.fixture
def analyst_headers():
    return ANALYST_HEADERS


@pytest.fixture
def analyst_2_headers():
    return ANALYST_2_HEADERS


@pytest.fixture
def chair_headers():
    return CHAIR_HEADERS


@pytest.fixture
def chair_2_headers():
    return CHAIR_2_HEADERS


@pytest.fixture
def officer_headers():
    return OFFICER_HEADERS


@pytest.fixture
def voter_headers():
    """Builder fixture: ``voter_headers("voter-3")`` yields the member
    headers under which that pool id must cast its ballot (voter_id must
    equal X-User-ID, PRD section 3.3)."""
    return make_committee_member_headers
