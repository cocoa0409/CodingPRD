"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_advertiser_agent_headers,
    make_officer_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def officer_alpha_headers():
    return TEST_USERS["officer_alpha_headers"]


@pytest.fixture
def officer_beta_headers():
    return TEST_USERS["officer_beta_headers"]


@pytest.fixture
def traffic_scheduler_headers():
    return TEST_USERS["traffic_scheduler_headers"]


@pytest.fixture
def public_complainant_headers():
    return TEST_USERS["public_complainant_headers"]


@pytest.fixture
def second_complainant_headers():
    return TEST_USERS["second_complainant_headers"]


@pytest.fixture
def advertiser_agent_headers_factory():
    """Build AdvertiserAgent headers bound to a specific advertiser id."""
    return make_advertiser_agent_headers


@pytest.fixture
def officer_headers_factory():
    """Build StationComplianceOfficer headers for a named principal."""
    return make_officer_headers
