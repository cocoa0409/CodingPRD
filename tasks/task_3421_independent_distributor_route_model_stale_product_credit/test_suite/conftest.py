"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns the server lifecycle and restarts the server before every
test, so each test starts against an empty database with the logical clock at
2026-09-01T00:00:00Z (PRD §2.4). Tests build all state through PRD-declared
endpoints via test_helpers.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    """CompanyAdmin operator headers (opaque identity, PRD §2.1)."""
    return TEST_USERS["company_admin_headers"]


@pytest.fixture
def route_ops_headers() -> dict:
    """RouteOpsManager operator headers (opaque identity, PRD §2.1)."""
    return TEST_USERS["route_ops_manager_headers"]


@pytest.fixture
def credit_analyst_headers() -> dict:
    """CreditAnalyst operator headers (opaque identity, PRD §2.1)."""
    return TEST_USERS["credit_analyst_headers"]


@pytest.fixture
def distributor_headers() -> dict:
    """Shared Distributor headers. Fallback only: never equals a real
    Distributor.id, so ownership-gated calls must use
    make_distributor_headers(distributor["id"]) instead (PRD §2.1)."""
    return TEST_USERS["distributor_headers"]
