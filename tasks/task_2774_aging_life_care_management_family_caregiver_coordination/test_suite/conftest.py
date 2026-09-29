"""Shared pytest fixtures for the aging-life-care coordination API suite.

The harness restarts the API server before every individual test, so each test
begins against an empty database and the logical clock at its startup default.
Every precondition below is therefore built from scratch through the endpoints
the PRD declares.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The shared HTTP client for the API under test."""
    return api_client


@pytest.fixture
def care_manager_headers():
    """`CareManager` headers carrying an opaque operator identifier.

    Ownership-gated calls must instead use `make_care_manager_headers` with the
    real `CareManager.id`.
    """
    return dict(TEST_USERS["care_manager_headers"])


@pytest.fixture
def practice_supervisor_headers():
    """`PracticeSupervisor` headers carrying an opaque operator identifier."""
    return dict(TEST_USERS["practice_supervisor_headers"])


@pytest.fixture
def family_decision_maker_headers():
    """`FamilyDecisionMaker` headers carrying an opaque operator identifier."""
    return dict(TEST_USERS["family_decision_maker_headers"])


@pytest.fixture
def billing_administrator_headers():
    """`BillingAdministrator` headers."""
    return dict(TEST_USERS["billing_administrator_headers"])


@pytest.fixture
def practice_admin_headers():
    """`PracticeAdmin` headers."""
    return dict(TEST_USERS["practice_admin_headers"])
