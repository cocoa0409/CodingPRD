"""Pytest fixtures exposing test_helpers infrastructure.

Importing test_helpers registers the PRD's error-id → HTTP-status map, so every
validate_error() call also cross-checks the transport status code.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def buyout_manager_headers():
    return TEST_USERS["buyout_manager_headers"]


@pytest.fixture
def buyout_manager_2_headers():
    """A second BuyoutManager operator — segregation of duties is by X-User-ID."""
    return TEST_USERS["buyout_manager_2_headers"]


@pytest.fixture
def project_executive_headers():
    return TEST_USERS["project_executive_headers"]


@pytest.fixture
def design_engineer_headers():
    return TEST_USERS["design_engineer_headers"]


@pytest.fixture
def owner_rep_headers():
    return TEST_USERS["owner_rep_headers"]


@pytest.fixture
def supplier_rep_headers():
    """SupplierRep headers for a supplier id that owns nothing.

    Ownership-gated calls must instead use make_supplier_rep_headers(supplier_id).
    """
    return TEST_USERS["supplier_rep_headers"]
