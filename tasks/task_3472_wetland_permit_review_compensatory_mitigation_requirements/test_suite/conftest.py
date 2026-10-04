"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns the server lifecycle and PYTHONPATH; tests import everything
else from `test_helpers` directly. For ownership-gated calls, build headers
with `make_applicant_headers(applicant["id"])` — never the shared
`applicant_headers` constant (see test_helpers.test_users).
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def applicant_headers():
    """Shared Applicant headers — safe only for tests whose outcome does not
    depend on owning the subject resource. Ownership-gated calls must use
    make_applicant_headers(applicant["id"]) instead."""
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def reviewer_2_headers():
    return TEST_USERS["reviewer_2_headers"]


@pytest.fixture
def district_engineer_headers():
    return TEST_USERS["district_engineer_headers"]


@pytest.fixture
def decision_engineer_headers():
    """DistrictEngineer whose id (de-9) never equals the default screener
    (rev-1), so the render-decision segregation-of-duties gate passes."""
    return TEST_USERS["decision_engineer_headers"]


@pytest.fixture
def agency_reviewer_headers():
    return TEST_USERS["agency_reviewer_headers"]


@pytest.fixture
def agency_reviewer_2_headers():
    return TEST_USERS["agency_reviewer_2_headers"]


@pytest.fixture
def officer_opener_headers():
    """EnforcementOfficer eo-1 — opens cases; may never confirm them."""
    return TEST_USERS["officer_opener_headers"]


@pytest.fixture
def officer_confirmer_headers():
    """EnforcementOfficer eo-2 — confirms/resolves cases opened by eo-1."""
    return TEST_USERS["officer_confirmer_headers"]


@pytest.fixture
def officer_3_headers():
    return TEST_USERS["officer_3_headers"]


@pytest.fixture
def no_auth_headers():
    """Empty header set: carries neither X-User-ID nor X-User-Role."""
    return {}
