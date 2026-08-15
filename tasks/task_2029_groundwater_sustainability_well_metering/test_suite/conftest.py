"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; tests assume the API is
already reachable at API_BASE_URL.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The runner owns server start/stop."""
    return api_client


@pytest.fixture
def well_owner_headers():
    """Shared WellOwner fallback — only for tests that do not exercise ownership."""
    return TEST_USERS["well_owner_headers"]


@pytest.fixture
def water_master_headers():
    return TEST_USERS["water_master_headers"]


@pytest.fixture
def enforcement_officer_headers():
    return TEST_USERS["enforcement_officer_headers"]


@pytest.fixture
def appeals_officer_headers():
    return TEST_USERS["appeals_officer_headers"]


@pytest.fixture
def state_regulator_headers():
    return TEST_USERS["state_regulator_headers"]
