"""Pre-built request headers for the four roles the PRD declares.

`ComplianceAdmin` and `AntitrustCounsel` carry opaque operator identifiers the
server never resolves as an entity id, so a shared constant is always safe for
them — although counsel identities matter for segregation of duties, which is
why `make_counsel_headers()` exists.

`BusinessLead` and `Employee` are identity-backed: a lead's `X-User-ID` is the
acting business unit's own `id`, and an employee's is the acting employee
record's own `id`. Every ownership-gated call must therefore build its headers
from the real entity id through `make_business_lead_headers()` /
`make_employee_headers()`; the shared constants below are only for calls whose
success does not depend on owning the subject resource.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "compliance_admin_headers": build_user_headers("admin-1", "ComplianceAdmin"),
    "antitrust_counsel_headers": build_user_headers("counsel-1", "AntitrustCounsel"),
    # Shared fallbacks — never use these where ownership is checked.
    "business_lead_headers": build_user_headers("lead-operator-1", "BusinessLead"),
    "employee_headers": build_user_headers("employee-operator-1", "Employee"),
}

ADMIN = TEST_USERS["compliance_admin_headers"]
COUNSEL = TEST_USERS["antitrust_counsel_headers"]
BUSINESS_LEAD = TEST_USERS["business_lead_headers"]
EMPLOYEE = TEST_USERS["employee_headers"]


def make_admin_headers(user_id: str) -> dict:
    """Headers for a named programme administrator."""
    return build_user_headers(user_id, "ComplianceAdmin")


def make_counsel_headers(user_id: str) -> dict:
    """Headers for a named counsel.

    The identity matters wherever segregation of duties is enforced: the
    counsel recorded as `legal_cleared_by_user_id` may not review the
    participation's minutes, and the counsel recorded as
    `minutes_reviewed_by_user_id` may not close that attendance's remediation.
    """
    return build_user_headers(user_id, "AntitrustCounsel")


def make_business_lead_headers(business_unit_id: str) -> dict:
    """Headers for the lead of a unit: X-User-ID is the unit's own id."""
    return build_user_headers(business_unit_id, "BusinessLead")


def make_employee_headers(employee_id: str) -> dict:
    """Headers for an individual: X-User-ID is the employee record's own id."""
    return build_user_headers(employee_id, "Employee")
