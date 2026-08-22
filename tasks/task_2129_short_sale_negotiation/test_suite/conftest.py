"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's responsibility."""
    return api_client


@pytest.fixture
def negotiator_headers():
    return TEST_USERS["negotiator_headers"]


@pytest.fixture
def listing_agent_headers():
    return TEST_USERS["listing_agent_headers"]


@pytest.fixture
def servicer_analyst_headers():
    return TEST_USERS["servicer_analyst_headers"]


@pytest.fixture
def second_analyst_headers():
    return TEST_USERS["second_analyst_headers"]


@pytest.fixture
def junior_lien_holder_headers():
    return TEST_USERS["junior_lien_holder_headers"]


@pytest.fixture
def mi_underwriter_headers():
    return TEST_USERS["mi_underwriter_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
