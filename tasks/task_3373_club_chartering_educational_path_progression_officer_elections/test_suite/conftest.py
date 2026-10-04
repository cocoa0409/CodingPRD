"""Pytest fixtures exposing the test infrastructure.

The runner owns server lifecycle (it restarts the server before every test) and
sets API_BASE_URL, so nothing here starts, stops or health-checks the server.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client pointed at the running server."""
    return api_client


@pytest.fixture
def whq_headers() -> dict:
    """Opaque WorldHeadquarters operator identity."""
    return TEST_USERS["world_headquarters_headers"]


@pytest.fixture
def member_headers() -> dict:
    """Member identity — only for calls with no ownership clause."""
    return TEST_USERS["member_headers"]


@pytest.fixture
def district_director_headers() -> dict:
    """DistrictDirector identity — only for calls with no ownership clause."""
    return TEST_USERS["district_director_headers"]
