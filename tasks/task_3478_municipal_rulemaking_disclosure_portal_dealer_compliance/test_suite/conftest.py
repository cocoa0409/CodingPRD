"""Pytest fixtures bridging the test_helpers package into the test suite.

The runner owns the server lifecycle and injects API_BASE_URL; the tests
assume a reachable server and a fresh deployment per test. These fixtures
only expose the shared API client and the prebuilt opaque-role header sets.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped shared API client (server lifecycle is the runner's)."""
    return api_client


@pytest.fixture
def officer_headers():
    return TEST_USERS["rulemaking_officer_headers"]


@pytest.fixture
def officer_alt_headers():
    return TEST_USERS["rulemaking_officer_alt_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]


@pytest.fixture
def portal_operator_headers():
    return TEST_USERS["portal_operator_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_alt_headers():
    return TEST_USERS["compliance_officer_alt_headers"]


@pytest.fixture
def exam_admin_headers():
    return TEST_USERS["exam_admin_headers"]


@pytest.fixture
def licensing_headers():
    return TEST_USERS["licensing_officer_headers"]


@pytest.fixture
def public_reader_headers():
    return TEST_USERS["public_reader_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]
