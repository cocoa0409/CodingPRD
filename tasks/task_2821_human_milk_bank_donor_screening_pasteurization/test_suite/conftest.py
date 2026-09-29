"""Shared pytest fixtures for the Human Milk Bank Screening Pasteurization suite.

The harness restarts the service before every individual test, so each test
opens against an empty database and a logical clock sitting at its startup
value of 2026-08-01T00:00:00Z. Nothing is shared between tests: every test
builds the donors, coolers, pools, runs, lots and orders it needs through the
documented endpoints.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The HTTP surface under test."""
    return api_client


@pytest.fixture
def admin_headers():
    """A MilkBankAdmin: subsidy programs, allocation cycles and the clock."""
    return TEST_USERS["admin"]


@pytest.fixture
def intake_headers():
    """An IntakeCoordinator: enrolment, health histories and cooler intake."""
    return TEST_USERS["intake"]


@pytest.fixture
def director_headers():
    """A MedicalDirector: serology, approvals, qualification and deferrals."""
    return TEST_USERS["medical_director"]


@pytest.fixture
def technician_headers():
    """A ProcessingTechnician: pools, the pasteurizer and bottling."""
    return TEST_USERS["technician"]


@pytest.fixture
def qa_headers():
    """The QualityAssuranceOfficer who records cultures."""
    return TEST_USERS["qa_officer"]


@pytest.fixture
def qa_releaser_headers():
    """A second QualityAssuranceOfficer, so lot release can clear the
    segregation-of-duties comparison against the culture recorder."""
    return TEST_USERS["qa_releaser"]


@pytest.fixture
def pharmacist_headers():
    """A DispensingPharmacist: fills, voids and allocation cycles."""
    return TEST_USERS["pharmacist"]


@pytest.fixture
def prescriber_headers():
    """A Prescriber: order submission and cancellation."""
    return TEST_USERS["prescriber"]
