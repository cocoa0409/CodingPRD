"""Pre-built role headers for every role the PRD declares.

`Employee` is the only role whose identity is backed by a persisted row, so
its headers must always be built from the acting employee's own `id` with
`make_employee_headers()`. The other six roles carry opaque operator
identifiers, so their shared constants below are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque operator identifiers reused across the suite so that
# manager_user_id / hr_partner_user_id comparisons are predictable.
WPO_USER_ID = "wpo-1"
HRBP_USER_ID = "hrbp-1"
MANAGER_USER_ID = "mgr-1"
SECOND_MANAGER_USER_ID = "mgr-2"
ACCOMMODATION_USER_ID = "acc-1"
AUDITOR_USER_ID = "aud-1"
SYSTEM_USER_ID = "sys-1"
SECOND_HRBP_USER_ID = "hrbp-2"


TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "workplace_program_office_headers": build_user_headers(
        WPO_USER_ID, UserRole.WORKPLACE_PROGRAM_OFFICE.value
    ),
    "hr_business_partner_headers": build_user_headers(
        HRBP_USER_ID, UserRole.HR_BUSINESS_PARTNER.value
    ),
    "people_manager_headers": build_user_headers(
        MANAGER_USER_ID, UserRole.PEOPLE_MANAGER.value
    ),
    "second_people_manager_headers": build_user_headers(
        SECOND_MANAGER_USER_ID, UserRole.PEOPLE_MANAGER.value
    ),
    "second_hr_business_partner_headers": build_user_headers(
        SECOND_HRBP_USER_ID, UserRole.HR_BUSINESS_PARTNER.value
    ),
    "accommodation_specialist_headers": build_user_headers(
        ACCOMMODATION_USER_ID, UserRole.ACCOMMODATION_SPECIALIST.value
    ),
    "compliance_auditor_headers": build_user_headers(
        AUDITOR_USER_ID, UserRole.COMPLIANCE_AUDITOR.value
    ),
    "system_integration_headers": build_user_headers(
        SYSTEM_USER_ID, UserRole.SYSTEM_INTEGRATION.value
    ),
    # Employee role: shared constant is a fallback for tests that never reach
    # an ownership comparison (for example a 403-on-wrong-role probe).
    "employee_headers": build_user_headers(
        "00000000-0000-4000-8000-0000000000ff", UserRole.EMPLOYEE.value
    ),
}


def make_employee_headers(employee_id: str) -> dict:
    """Headers for the `Employee` role.

    Pass the acting employee's own `id`: on every ownership-gated call the
    server compares the resource's `employee_id` to `X-User-ID`.
    """
    return build_user_headers(employee_id, UserRole.EMPLOYEE.value)


def make_people_manager_headers(user_id: str) -> dict:
    """Headers for a specific `PeopleManager` operator identity."""
    return build_user_headers(user_id, UserRole.PEOPLE_MANAGER.value)


def make_hr_business_partner_headers(user_id: str) -> dict:
    """Headers for a specific `HRBusinessPartner` operator identity."""
    return build_user_headers(user_id, UserRole.HR_BUSINESS_PARTNER.value)


def make_workplace_program_office_headers(user_id: str) -> dict:
    """Headers for a specific `WorkplaceProgramOffice` operator identity."""
    return build_user_headers(user_id, UserRole.WORKPLACE_PROGRAM_OFFICE.value)


def make_compliance_auditor_headers(user_id: str) -> dict:
    """Headers for a specific `ComplianceAuditor` operator identity."""
    return build_user_headers(user_id, UserRole.COMPLIANCE_AUDITOR.value)


def make_accommodation_specialist_headers(user_id: str) -> dict:
    """Headers for a specific `AccommodationSpecialist` operator identity."""
    return build_user_headers(user_id, UserRole.ACCOMMODATION_SPECIALIST.value)


def make_system_integration_headers(user_id: str) -> dict:
    """Headers for a specific `SystemIntegration` operator identity."""
    return build_user_headers(user_id, UserRole.SYSTEM_INTEGRATION.value)


def headers_for_role(role: str, user_id: str = None) -> dict:
    """Build headers for an arbitrary role name, for role-sweep tests."""
    defaults = {
        UserRole.WORKPLACE_PROGRAM_OFFICE.value: WPO_USER_ID,
        UserRole.HR_BUSINESS_PARTNER.value: HRBP_USER_ID,
        UserRole.PEOPLE_MANAGER.value: MANAGER_USER_ID,
        UserRole.ACCOMMODATION_SPECIALIST.value: ACCOMMODATION_USER_ID,
        UserRole.COMPLIANCE_AUDITOR.value: AUDITOR_USER_ID,
        UserRole.SYSTEM_INTEGRATION.value: SYSTEM_USER_ID,
        UserRole.EMPLOYEE.value: "00000000-0000-4000-8000-0000000000ff",
    }
    return build_user_headers(user_id or defaults[role], role)


# Headers with no acting user at all, for the authentication band.
NO_IDENTITY_HEADERS = {"X-User-Role": UserRole.WORKPLACE_PROGRAM_OFFICE.value}
EMPTY_IDENTITY_HEADERS = {
    "X-User-ID": "",
    "X-User-Role": UserRole.WORKPLACE_PROGRAM_OFFICE.value,
}
