"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def harbor_admin_headers():
    return TEST_USERS["harbor_admin_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def marine_inspector_headers():
    return TEST_USERS["marine_inspector_headers"]


@pytest.fixture
def rider_headers():
    return TEST_USERS["rider_headers"]


@pytest.fixture
def rider_bob_headers():
    return TEST_USERS["rider_bob_headers"]


@pytest.fixture
def rider_cid_headers():
    return TEST_USERS["rider_cid_headers"]


@pytest.fixture
def fare_auditor_headers():
    return TEST_USERS["fare_auditor_headers"]


@pytest.fixture
def fare_auditor_alt_headers():
    return TEST_USERS["fare_auditor_alt_headers"]


@pytest.fixture
def vessel_master_headers():
    """Fallback VesselMaster headers. Movement calls must instead use
    make_vessel_master_headers(crew['id'])."""
    return TEST_USERS["vessel_master_headers"]
