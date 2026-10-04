"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle (per-test restart) is owned by prd-bench-local-runner;
this module only wires the generated helpers into pytest fixtures.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server is managed by the runner."""
    return api_client


@pytest.fixture
def gsa_admin_headers():
    return TEST_USERS["gsa_admin_headers"]


@pytest.fixture
def gsa_leasing_officer_headers():
    return TEST_USERS["gsa_leasing_officer_headers"]


@pytest.fixture
def gsa_property_manager_headers():
    return TEST_USERS["gsa_property_manager_headers"]


@pytest.fixture
def agency_manager_headers():
    """Fallback AgencyManager identity for calls that are not ownership-gated."""
    return TEST_USERS["agency_manager_headers"]


@pytest.fixture
def lessor_rep_headers():
    return TEST_USERS["lessor_rep_headers"]
