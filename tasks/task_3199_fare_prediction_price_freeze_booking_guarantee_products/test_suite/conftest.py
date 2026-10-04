"""Pytest fixtures exposing test_helpers infrastructure.

The server's lifecycle (start, readiness, restart before each test) is owned by
prd-bench-local-runner; this module only wires the client and the role headers
into pytest.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def traveler_headers():
    return TEST_USERS["traveler_headers"]


@pytest.fixture
def traveler_otis_headers():
    return TEST_USERS["traveler_otis_headers"]


@pytest.fixture
def traveler_rae_headers():
    return TEST_USERS["traveler_rae_headers"]


@pytest.fixture
def traveler_impostor_headers():
    return TEST_USERS["traveler_impostor_headers"]


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]


@pytest.fixture
def risk_analyst_headers():
    return TEST_USERS["risk_analyst_headers"]


@pytest.fixture
def adjuster_ingrid_headers():
    return TEST_USERS["adjuster_ingrid_headers"]


@pytest.fixture
def adjuster_pavel_headers():
    return TEST_USERS["adjuster_pavel_headers"]


@pytest.fixture
def adjuster_rosa_headers():
    return TEST_USERS["adjuster_rosa_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def system_operator_headers():
    return TEST_USERS["system_operator_headers"]