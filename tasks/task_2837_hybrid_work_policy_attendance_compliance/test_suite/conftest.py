"""Pytest fixtures exposing the shared test infrastructure to every test file."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture(scope="session")
def workplace_program_office_headers() -> dict:
    """Headers for the `WorkplaceProgramOffice` role."""
    return TEST_USERS["workplace_program_office_headers"]


@pytest.fixture(scope="session")
def hr_business_partner_headers() -> dict:
    """Headers for the `HRBusinessPartner` role."""
    return TEST_USERS["hr_business_partner_headers"]


@pytest.fixture(scope="session")
def people_manager_headers() -> dict:
    """Headers for the `PeopleManager` role, acting as operator mgr-1."""
    return TEST_USERS["people_manager_headers"]


@pytest.fixture(scope="session")
def second_people_manager_headers() -> dict:
    """Headers for a second `PeopleManager` operator identity, mgr-2."""
    return TEST_USERS["second_people_manager_headers"]


@pytest.fixture(scope="session")
def second_hr_business_partner_headers() -> dict:
    """Headers for a second `HRBusinessPartner` operator identity, hrbp-2."""
    return TEST_USERS["second_hr_business_partner_headers"]


@pytest.fixture(scope="session")
def accommodation_specialist_headers() -> dict:
    """Headers for the `AccommodationSpecialist` role."""
    return TEST_USERS["accommodation_specialist_headers"]


@pytest.fixture(scope="session")
def compliance_auditor_headers() -> dict:
    """Headers for the `ComplianceAuditor` role."""
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture(scope="session")
def system_integration_headers() -> dict:
    """Headers for the `SystemIntegration` telemetry feed role."""
    return TEST_USERS["system_integration_headers"]


@pytest.fixture(scope="session")
def employee_headers() -> dict:
    """Fallback headers for the `Employee` role.

    `Employee` identity is backed by a persisted row, so ownership-gated calls
    must build headers from the acting employee's own id instead.
    """
    return TEST_USERS["employee_headers"]
