"""Pytest wiring for the Identity Protection & Return Fraud suite.

The harness restarts the API server before every test, so each test builds
its own world through the public API. The runner injects API_BASE_URL and
PYTHONPATH, so test_helpers is importable without sys.path hacks.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """API client aimed at the server under test (lifecycle managed by the
    runner)."""
    return api_client


@pytest.fixture
def taxpayer_headers():
    return TEST_USERS["taxpayer_headers"]


@pytest.fixture
def tax_preparer_headers():
    return TEST_USERS["tax_preparer_headers"]


@pytest.fixture
def verification_agent_headers():
    return TEST_USERS["verification_agent_headers"]


@pytest.fixture
def fraud_analyst_headers():
    return TEST_USERS["fraud_analyst_headers"]


@pytest.fixture
def taxpayer_advocate_headers():
    return TEST_USERS["taxpayer_advocate_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]
