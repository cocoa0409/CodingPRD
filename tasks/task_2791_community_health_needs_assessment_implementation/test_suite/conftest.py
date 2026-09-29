"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def officer_headers():
    """A `CommunityBenefitOfficer` who runs the assessment cycle end to end."""
    return TEST_USERS["officer"]


@pytest.fixture
def officer_2_headers():
    """A second `CommunityBenefitOfficer`, for segregation-of-duties pairings."""
    return TEST_USERS["officer_2"]


@pytest.fixture
def steward_headers():
    """A `DataSteward`, the sole author and retractor of observations."""
    return TEST_USERS["steward"]


@pytest.fixture
def board_headers():
    """A `BoardChair`, the only role that may adopt or defer."""
    return TEST_USERS["board"]


@pytest.fixture
def compliance_headers():
    """A `ComplianceOfficer`, who locks the report, files and closes the cycle."""
    return TEST_USERS["compliance"]


@pytest.fixture
def compliance_2_headers():
    """A second `ComplianceOfficer`, for segregation-of-duties pairings."""
    return TEST_USERS["compliance_2"]


@pytest.fixture
def public_headers():
    """A `PublicViewer`, the read-only public availability surface."""
    return TEST_USERS["public"]
