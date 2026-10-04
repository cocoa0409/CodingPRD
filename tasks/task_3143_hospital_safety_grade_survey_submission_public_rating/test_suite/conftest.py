"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["rating_admin_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def engine_headers():
    return TEST_USERS["engine_headers"]


@pytest.fixture
def reader_headers():
    return TEST_USERS["reader_headers"]


@pytest.fixture
def respondent_headers():
    return TEST_USERS["respondent_headers"]


@pytest.fixture
def purchaser_headers():
    return TEST_USERS["purchaser_headers"]