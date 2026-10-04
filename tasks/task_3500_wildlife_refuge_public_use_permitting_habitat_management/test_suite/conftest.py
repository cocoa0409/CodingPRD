"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; tests import everything
from test_helpers and assume the server is reachable at API_BASE_URL with
the logical clock at 2026-09-01T00:00:00Z (PRD §2.5).
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def refuge_manager_headers() -> dict:
    return TEST_USERS["refuge_manager_headers"]


@pytest.fixture
def biologist_headers() -> dict:
    return TEST_USERS["biologist_headers"]


@pytest.fixture
def permit_officer_headers() -> dict:
    return TEST_USERS["permit_officer_headers"]


@pytest.fixture
def volunteer_coordinator_headers() -> dict:
    return TEST_USERS["volunteer_coordinator_headers"]


@pytest.fixture
def law_enforcement_officer_headers() -> dict:
    return TEST_USERS["law_enforcement_officer_headers"]


@pytest.fixture
def state_agency_partner_headers() -> dict:
    return TEST_USERS["state_agency_partner_headers"]


@pytest.fixture
def anonymous_headers() -> dict:
    return TEST_USERS["anonymous_headers"]
