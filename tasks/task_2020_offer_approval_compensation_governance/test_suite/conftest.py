"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def hr_admin_headers():
    return TEST_USERS["hr_admin_headers"]


@pytest.fixture
def hm_headers():
    return TEST_USERS["hm_headers"]


@pytest.fixture
def hm2_headers():
    return TEST_USERS["hm2_headers"]


@pytest.fixture
def recruiter_headers():
    return TEST_USERS["recruiter_headers"]


@pytest.fixture
def comp_analyst_headers():
    return TEST_USERS["comp_analyst_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def vp_headers():
    return TEST_USERS["vp_headers"]


@pytest.fixture
def screener_headers():
    return TEST_USERS["screener_headers"]
