"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS, make_licensee_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def staff_headers():
    """EditorialStaff — an opaque operator identity."""
    return TEST_USERS["editorial_staff_headers"]


@pytest.fixture
def chair_headers():
    """EditorialPanelChair — an opaque operator identity."""
    return TEST_USERS["editorial_panel_chair_headers"]


@pytest.fixture
def licensing_headers():
    """LicensingOfficer — an opaque operator identity."""
    return TEST_USERS["licensing_officer_headers"]


@pytest.fixture
def reviewer_headers():
    """CommitteeReviewer shared constant (not ownership-gated)."""
    return TEST_USERS["committee_reviewer_headers"]


@pytest.fixture
def licensee_headers():
    """Licensee shared constant (not ownership-gated)."""
    return TEST_USERS["licensee_headers"]


@pytest.fixture
def applicant_headers():
    """ChangeApplicant shared constant (not ownership-gated)."""
    return TEST_USERS["change_applicant_headers"]