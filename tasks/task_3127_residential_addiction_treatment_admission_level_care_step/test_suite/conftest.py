"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    """A `PlatformAdmin` caller; its `X-User-ID` is opaque and never looked up."""
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def clinical_director_headers():
    """A `ClinicalDirector` caller; its `X-User-ID` is opaque and never looked up."""
    return TEST_USERS["clinical_director_headers"]


@pytest.fixture
def utilization_reviewer_headers():
    """A `UtilizationReviewer` caller; its `X-User-ID` is opaque and never looked up."""
    return TEST_USERS["utilization_reviewer_headers"]


@pytest.fixture
def intake_nurse_headers():
    """An `AdmissionsIntakeNurse` caller; its `X-User-ID` is opaque and never looked up."""
    return TEST_USERS["intake_nurse_headers"]


@pytest.fixture
def alumni_coordinator_headers():
    """An `AlumniCoordinator` caller; its `X-User-ID` is opaque and never looked up."""
    return TEST_USERS["alumni_coordinator_headers"]


@pytest.fixture
def read_headers():
    """An `Any` caller, restricted to the read surface."""
    return TEST_USERS["read_headers"]


@pytest.fixture
def unknown_clinician_headers():
    """A `Clinician` caller whose `X-User-ID` matches no existing clinician row."""
    return TEST_USERS["unknown_clinician_headers"]
