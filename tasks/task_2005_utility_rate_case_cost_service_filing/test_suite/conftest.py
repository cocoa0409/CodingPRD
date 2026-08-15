"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def filer_headers():
    return TEST_USERS["utility_filer_alice"]


@pytest.fixture
def filer_bob_headers():
    return TEST_USERS["utility_filer_bob"]


@pytest.fixture
def staff_headers():
    return TEST_USERS["commission_staff"]


@pytest.fixture
def alj_headers():
    return TEST_USERS["alj"]


@pytest.fixture
def intervenor_rep_headers():
    return TEST_USERS["intervenor_rep"]
