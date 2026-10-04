"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def board_headers():
    return TEST_USERS["board_headers"]


@pytest.fixture
def studio_rep_headers():
    return TEST_USERS["studio_rep_headers"]


@pytest.fixture
def critic_headers():
    return TEST_USERS["critic_headers"]


@pytest.fixture
def audience_member_headers():
    return TEST_USERS["audience_member_headers"]
