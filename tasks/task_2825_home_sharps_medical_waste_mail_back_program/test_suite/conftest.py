"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def intake_technician_headers():
    return TEST_USERS["intake_technician_headers"]


@pytest.fixture
def second_intake_technician_headers():
    return TEST_USERS["second_intake_technician_headers"]


@pytest.fixture
def destruction_officer_headers():
    return TEST_USERS["destruction_officer_headers"]


@pytest.fixture
def second_destruction_officer_headers():
    return TEST_USERS["second_destruction_officer_headers"]


@pytest.fixture
def sponsor_representative_headers():
    """Unbound SponsorRepresentative headers. Ownership-gated calls must use
    `make_sponsor_representative_headers(sponsor["id"])` instead."""
    return TEST_USERS["sponsor_representative_headers"]


@pytest.fixture
def patient_headers():
    """Unbound Patient headers. Ownership-gated calls must use
    `make_patient_headers(patient["id"])` instead."""
    return TEST_USERS["patient_headers"]
