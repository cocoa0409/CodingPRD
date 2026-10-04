"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client, make_client_admin_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def onboarder_headers():
    return TEST_USERS["onboarder_headers"]


@pytest.fixture
def treasury_headers():
    return TEST_USERS["treasury_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def filer_alpha_headers():
    return TEST_USERS["filer_alpha_headers"]


@pytest.fixture
def filer_beta_headers():
    return TEST_USERS["filer_beta_headers"]


@pytest.fixture
def client_admin_headers_factory():
    return make_client_admin_headers
