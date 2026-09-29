"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client, setup_base_config


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def rep_headers():
    return TEST_USERS["rep_headers"]


@pytest.fixture
def other_rep_headers():
    return TEST_USERS["other_rep_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def other_director_headers():
    return TEST_USERS["other_director_headers"]


@pytest.fixture
def vp_headers():
    return TEST_USERS["vp_headers"]


@pytest.fixture
def cfo_headers():
    return TEST_USERS["cfo_headers"]


@pytest.fixture
def legal_headers():
    return TEST_USERS["legal_headers"]


@pytest.fixture
def accountant_headers():
    return TEST_USERS["accountant_headers"]


@pytest.fixture
def base(api):
    """The configured desk: an ACTIVE policy with its matrix, the catalogue,
    the Core Platform quantity bands, the Core -> Support bundle rule and one
    customer account."""
    return setup_base_config(api)
