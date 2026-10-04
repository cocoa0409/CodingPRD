"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_dsp_headers, make_member_headers, make_admin_headers, make_public_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin2_headers():
    return TEST_USERS["admin2_headers"]


@pytest.fixture
def public_headers():
    return TEST_USERS["public_headers"]


@pytest.fixture
def dsp_user_headers():
    return TEST_USERS["dsp_user_headers"]


@pytest.fixture
def member_user_headers():
    return TEST_USERS["member_user_headers"]
