"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ADMIN,
    MODERATOR,
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped client; server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def admin_headers():
    return ADMIN


@pytest.fixture
def moderator_headers():
    return MODERATOR


@pytest.fixture
def talent_headers_shared():
    return TEST_USERS["talent_headers"]


@pytest.fixture
def buyer_headers_shared():
    return TEST_USERS["buyer_headers"]
