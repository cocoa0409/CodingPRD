"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import (
    APPRAISER,
    LOAN_OFFICER,
    PROGRAM_ADMIN,
    TEST_USERS,
    UNDERWRITER,
    VETERAN,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def veteran_headers():
    return VETERAN


@pytest.fixture
def loan_officer_headers():
    return LOAN_OFFICER


@pytest.fixture
def underwriter_headers():
    return UNDERWRITER


@pytest.fixture
def appraiser_headers():
    return APPRAISER


@pytest.fixture
def program_admin_headers():
    return PROGRAM_ADMIN


@pytest.fixture
def test_users():
    return TEST_USERS
