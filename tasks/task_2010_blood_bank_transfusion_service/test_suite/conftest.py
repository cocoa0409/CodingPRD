"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def tech_a_headers():
    return TEST_USERS["tech_a_headers"]


@pytest.fixture
def tech_b_headers():
    return TEST_USERS["tech_b_headers"]


@pytest.fixture
def tech_c_headers():
    return TEST_USERS["tech_c_headers"]


@pytest.fixture
def doc_1_headers():
    return TEST_USERS["doc_1_headers"]


@pytest.fixture
def doc_2_headers():
    return TEST_USERS["doc_2_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def qo_1_headers():
    return TEST_USERS["qo_1_headers"]


@pytest.fixture
def qo_2_headers():
    return TEST_USERS["qo_2_headers"]
