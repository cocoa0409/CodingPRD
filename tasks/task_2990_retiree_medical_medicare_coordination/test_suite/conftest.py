"""Pytest fixtures exposing the test_helpers infrastructure.

The runner restarts the server with an empty database before every test, so no
fixture here seeds data: the header fixtures are pure constants and every test
builds its own state through the API.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """BenefitsAdmin admin-01: plan-year and plan-option catalogue, clock, sweep."""
    return TEST_USERS["benefits_admin_headers"]


@pytest.fixture
def admin2_headers():
    return TEST_USERS["benefits_admin_2_headers"]


@pytest.fixture
def analyst_headers():
    """EligibilityAnalyst analyst-01: creates retirees and determinations."""
    return TEST_USERS["eligibility_analyst_headers"]


@pytest.fixture
def analyst2_headers():
    """EligibilityAnalyst analyst-02: certifies what analyst-01 created."""
    return TEST_USERS["eligibility_analyst_2_headers"]


@pytest.fixture
def analyst3_headers():
    return TEST_USERS["eligibility_analyst_3_headers"]


@pytest.fixture
def counselor_headers():
    """EnrollmentCounselor counselor-01: submits elections."""
    return TEST_USERS["enrollment_counselor_headers"]


@pytest.fixture
def counselor2_headers():
    """EnrollmentCounselor counselor-02: reviews and decides elections."""
    return TEST_USERS["enrollment_counselor_2_headers"]


@pytest.fixture
def counselor3_headers():
    return TEST_USERS["enrollment_counselor_3_headers"]


@pytest.fixture
def hra_admin_headers():
    """HraAdministrator hra-admin-01: opens accounts and closes plan years."""
    return TEST_USERS["hra_administrator_headers"]


@pytest.fixture
def hra_admin2_headers():
    """HraAdministrator hra-admin-02: reviews claims."""
    return TEST_USERS["hra_administrator_2_headers"]


@pytest.fixture
def billing_headers():
    """BillingClerk billing-01: invoices, payments and claim settlement."""
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def billing2_headers():
    return TEST_USERS["billing_clerk_2_headers"]


@pytest.fixture
def actuary_headers():
    """Actuary actuary-01: attests plan values and runs liability valuations."""
    return TEST_USERS["actuary_headers"]


@pytest.fixture
def actuary2_headers():
    return TEST_USERS["actuary_2_headers"]


@pytest.fixture
def compliance_headers():
    """ComplianceOfficer compliance-01: certifies prescription subsidy values."""
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance2_headers():
    return TEST_USERS["compliance_officer_2_headers"]


@pytest.fixture
def retiree_headers():
    """Retiree role with an id that belongs to no Retiree row.

    Only safe where the expected outcome does not depend on ownership; every
    ownership-gated call must use make_retiree_headers(<real retiree id>).
    """
    return TEST_USERS["retiree_headers"]
