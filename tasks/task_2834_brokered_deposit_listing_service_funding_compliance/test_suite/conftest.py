"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def system_admin_headers() -> dict:
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def funding_desk_headers() -> dict:
    return TEST_USERS["funding_desk_headers"]


@pytest.fixture
def compliance_headers() -> dict:
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def treasury_headers() -> dict:
    return TEST_USERS["treasury_headers"]


@pytest.fixture
def examiner_headers() -> dict:
    return TEST_USERS["examiner_headers"]


@pytest.fixture
def system_admin_alt_headers() -> dict:
    return TEST_USERS["system_admin_alt_headers"]


@pytest.fixture
def funding_desk_alt_headers() -> dict:
    return TEST_USERS["funding_desk_alt_headers"]


@pytest.fixture
def compliance_alt_headers() -> dict:
    return TEST_USERS["compliance_alt_headers"]


@pytest.fixture
def treasury_alt_headers() -> dict:
    return TEST_USERS["treasury_alt_headers"]


@pytest.fixture
def examiner_alt_headers() -> dict:
    return TEST_USERS["examiner_alt_headers"]
