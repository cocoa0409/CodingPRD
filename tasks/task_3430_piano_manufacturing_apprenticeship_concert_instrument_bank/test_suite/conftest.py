"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; tests assume the server is
already reachable at API_BASE_URL. Entity-backed roles (MasterCraftsman,
Apprentice, Artist) resolve their X-User-ID against real entities, so tests
needing identity should prefer the make_*_headers builders from test_helpers.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def workshop_manager_headers():
    return TEST_USERS["workshop_manager_headers"]


@pytest.fixture
def master_craftsman_headers():
    return TEST_USERS["master_craftsman_headers"]


@pytest.fixture
def apprentice_headers():
    return TEST_USERS["apprentice_headers"]


@pytest.fixture
def artist_liaison_headers():
    return TEST_USERS["artist_liaison_headers"]


@pytest.fixture
def artist_headers():
    return TEST_USERS["artist_headers"]
