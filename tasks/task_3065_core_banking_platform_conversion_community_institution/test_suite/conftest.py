"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def pm_headers():
    return TEST_USERS["pm_headers"]


@pytest.fixture
def ce_headers():
    return TEST_USERS["ce_headers"]


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]


@pytest.fixture
def trainer_headers():
    return TEST_USERS["trainer_headers"]


@pytest.fixture
def co_headers():
    return TEST_USERS["co_headers"]


@pytest.fixture
def vtl_headers():
    return TEST_USERS["vtl_headers"]


@pytest.fixture
def fc_headers():
    return TEST_USERS["fc_headers"]
