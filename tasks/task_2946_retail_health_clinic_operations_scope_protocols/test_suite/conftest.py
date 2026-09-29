"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """ClinicAdmin: reference data, staffing, sampling, voids and the clock."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def front_desk_headers():
    """FrontDeskAgent: patient registration, queue intake, eligibility."""
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def unresolvable_clinician_headers():
    """A Clinician identity that resolves to no row, for identity probes only."""
    return TEST_USERS["clinician_headers"]


@pytest.fixture
def unresolvable_physician_headers():
    """A CollaboratingPhysician identity that resolves to no row."""
    return TEST_USERS["physician_headers"]


@pytest.fixture
def unresolvable_patient_headers():
    """A Patient identity that resolves to no row."""
    return TEST_USERS["patient_headers"]
