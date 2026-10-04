"""Pytest fixtures exposing the generated infrastructure.

The API server's lifecycle and API_BASE_URL are owned by the test runner, which
restarts the server before every individual test. Every fixture here therefore
starts from an empty database.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS, make_lender_headers, make_servicer_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def borrower_headers():
    return TEST_USERS["borrower_headers"]


@pytest.fixture
def lender_headers():
    return TEST_USERS["lender_headers"]


@pytest.fixture
def servicer_headers():
    return TEST_USERS["servicer_headers"]


@pytest.fixture
def lender_header_builder():
    return make_lender_headers


@pytest.fixture
def servicer_header_builder():
    return make_servicer_headers