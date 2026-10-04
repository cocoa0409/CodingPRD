"""Pytest fixtures exposing the test infrastructure.

Server lifecycle (start, restart, teardown) belongs to prd-bench-local-runner;
this file only bridges test_helpers into pytest fixtures.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The runner guarantees the server is reachable
    at API_BASE_URL before each test."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def physician_headers():
    return TEST_USERS["physician_headers"]


@pytest.fixture
def nurse_headers():
    return TEST_USERS["nurse_headers"]


@pytest.fixture
def counselor_headers():
    return TEST_USERS["counselor_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["medical_director_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["regulatory_auditor_headers"]