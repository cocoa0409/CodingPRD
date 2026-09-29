"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def sales_engineer_headers():
    """A sales engineer, who configures and prices bids."""
    return TEST_USERS["sales_engineer_headers"]


@pytest.fixture
def contracts_admin_headers():
    """A contracts administrator, who closes solicitations and books deliveries."""
    return TEST_USERS["contracts_admin_headers"]


@pytest.fixture
def contracts_admin_2_headers():
    """A second contracts administrator, needed wherever duties are segregated."""
    return TEST_USERS["contracts_admin_2_headers"]


@pytest.fixture
def plant_scheduler_headers():
    """A plant scheduler, who owns lines, bays, slots and the build progression."""
    return TEST_USERS["plant_scheduler_headers"]


@pytest.fixture
def quality_inspector_headers():
    """A quality inspector, who schedules and records verifications."""
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def quality_inspector_2_headers():
    """A second quality inspector, for measurements a different identity must sign."""
    return TEST_USERS["quality_inspector_2_headers"]


@pytest.fixture
def compliance_officer_headers():
    """A compliance officer, who publishes profiles, certifies buses and runs recalls."""
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_2_headers():
    """A second compliance officer, for certifications a different identity must sign."""
    return TEST_USERS["compliance_officer_2_headers"]


@pytest.fixture
def dealer_agent_headers():
    """A dealer agent bound to no dealer, for calls that are not ownership-gated."""
    return TEST_USERS["dealer_agent_headers"]
