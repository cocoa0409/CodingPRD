"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns server lifecycle, API_BASE_URL injection, and PYTHONPATH —
these fixtures are thin bridges. Composite setup helpers live in
test_helpers.fixtures and are imported directly by test modules.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server is managed (and rebooted
    per test) by the runner; this client only holds the base URL."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def registrant_alice_headers():
    return TEST_USERS["registrant_alice_headers"]


@pytest.fixture
def registrant_bob_headers():
    return TEST_USERS["registrant_bob_headers"]


@pytest.fixture
def reviewer_1_headers():
    return TEST_USERS["reviewer_1_headers"]


@pytest.fixture
def reviewer_2_headers():
    return TEST_USERS["reviewer_2_headers"]


@pytest.fixture
def assessor_1_headers():
    return TEST_USERS["assessor_1_headers"]


@pytest.fixture
def assessor_2_headers():
    return TEST_USERS["assessor_2_headers"]


@pytest.fixture
def state_agency_headers():
    return TEST_USERS["state_agency_headers"]


@pytest.fixture
def certification_authority_headers():
    return TEST_USERS["certification_authority_headers"]
