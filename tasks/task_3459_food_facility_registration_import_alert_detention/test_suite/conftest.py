"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle is managed by the runner; every test starts against an
empty database behind a freshly restarted server.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def facility_owner_headers():
    """Fallback only — never for ownership-gated calls (see test_helpers)."""
    return TEST_USERS["facility_owner_headers"]


@pytest.fixture
def importer_headers():
    """Fallback only — never for ownership-gated calls (see test_helpers)."""
    return TEST_USERS["importer_headers"]


@pytest.fixture
def entry_reviewer_headers():
    return TEST_USERS["entry_reviewer_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_two_headers():
    return TEST_USERS["compliance_officer_two_headers"]


@pytest.fixture
def field_inspector_headers():
    return TEST_USERS["field_inspector_headers"]


@pytest.fixture
def recall_coordinator_headers():
    return TEST_USERS["recall_coordinator_headers"]
