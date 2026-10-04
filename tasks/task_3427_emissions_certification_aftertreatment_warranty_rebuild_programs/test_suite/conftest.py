"""Pytest fixtures exposing the test_helpers infrastructure.

The runner (prd-bench-local-runner) owns server lifecycle, API_BASE_URL
injection and PYTHONPATH setup; these fixtures only bridge test_helpers into
pytest. The server is restarted before every test, so every test starts
against an empty database with the logical clock at its startup default.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    """PlatformAdmin (opaque role)."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def engineer_headers() -> dict:
    """CertificationEngineer (opaque role)."""
    return TEST_USERS["engineer_headers"]


@pytest.fixture
def officer_headers() -> dict:
    """RegulatoryOfficer (opaque role)."""
    return TEST_USERS["officer_headers"]


@pytest.fixture
def adjudicator_headers() -> dict:
    """WarrantyAdjudicator (opaque role)."""
    return TEST_USERS["adjudicator_headers"]


@pytest.fixture
def planner_headers() -> dict:
    """RemanPlanner (opaque role)."""
    return TEST_USERS["planner_headers"]


@pytest.fixture
def fleet_manager_headers() -> dict:
    """FleetManager fallback headers for tests that do NOT exercise ownership.
    For ownership-gated calls build headers from the acting fleet's id with
    test_helpers.make_fleet_manager_headers(fleet["id"])."""
    return TEST_USERS["fleet_manager_headers"]


@pytest.fixture
def service_advisor_headers() -> dict:
    """ServiceAdvisor fallback headers for tests that do NOT exercise
    ownership. For ownership-gated calls use
    test_helpers.make_service_advisor_headers(center["id"])."""
    return TEST_USERS["service_advisor_headers"]
