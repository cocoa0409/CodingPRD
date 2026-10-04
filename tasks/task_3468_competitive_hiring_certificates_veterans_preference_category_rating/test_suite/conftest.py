"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; tests hit the API at
API_BASE_URL through the shared client. Role-header fixtures mirror the
PRD's declared roles (§2.1); most tests instead use the module-level
HR/HM/SO/OPM/ADMIN constants and the make_*_headers builders exported
from test_helpers directly.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def hr_specialist_headers():
    return TEST_USERS["hr_specialist_headers"]


@pytest.fixture
def hiring_manager_headers():
    return TEST_USERS["hiring_manager_headers"]


@pytest.fixture
def sme_headers():
    return TEST_USERS["sme_headers"]


@pytest.fixture
def selecting_official_headers():
    return TEST_USERS["selecting_official_headers"]


@pytest.fixture
def opm_delegate_headers():
    return TEST_USERS["opm_delegate_headers"]


@pytest.fixture
def suitability_reviewer_headers():
    return TEST_USERS["suitability_reviewer_headers"]


@pytest.fixture
def security_adjudicator_headers():
    return TEST_USERS["security_adjudicator_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
