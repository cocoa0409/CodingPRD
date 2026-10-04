"""Pytest fixtures exposing the test_helpers infrastructure.

Server lifecycle (start, stop, per-test restart) belongs to the runner; these
fixtures only wire up the client and the four role identity headers.
"""

import pytest

from test_helpers import api_client, ApiClient, TEST_USERS, make_franchisee_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client pointing at the running server."""
    return api_client


@pytest.fixture
def admin_headers():
    """FranchisorAdmin: opaque back-office identity."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def auditor_headers():
    """FieldAuditor: opaque identity that records physical counts."""
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def commissary_headers():
    """Commissary: opaque dispatch identity."""
    return TEST_USERS["commissary_headers"]


@pytest.fixture
def franchisee_headers():
    """Shared Franchisee identity -- only for calls that are not ownership-gated."""
    return TEST_USERS["franchisee_headers"]


@pytest.fixture
def as_franchisee():
    """Builder for an ownership-gated Franchisee identity."""
    return make_franchisee_headers