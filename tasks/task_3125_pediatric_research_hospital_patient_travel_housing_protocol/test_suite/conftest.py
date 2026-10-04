"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; this file only bridges.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS, set_clock

CLOCK_START = "2026-09-01T00:00:00Z"


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def logical_clock():
    """Set the logical clock to the program's documented startup instant."""
    return set_clock(CLOCK_START)


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def protocol_coordinator_headers():
    return TEST_USERS["protocol_coordinator_headers"]


@pytest.fixture
def irb_reviewer_headers():
    return TEST_USERS["irb_reviewer_headers"]


@pytest.fixture
def intake_coordinator_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def housing_coordinator_headers():
    return TEST_USERS["housing_coordinator_headers"]


@pytest.fixture
def patient_support_officer_headers():
    return TEST_USERS["patient_support_officer_headers"]


@pytest.fixture
def affiliate_clinic_coordinator_headers():
    return TEST_USERS["affiliate_clinic_coordinator_headers"]


@pytest.fixture
def survivorship_coordinator_headers():
    return TEST_USERS["survivorship_coordinator_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]