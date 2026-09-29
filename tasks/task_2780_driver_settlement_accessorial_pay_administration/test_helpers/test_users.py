"""
Test identities.

The specification's segregation-of-duties rules compare the acting X-User-ID
against the identity stored on the record, so a single shared identity would make
prepare -> approve -> pay unrunnable. Each office role therefore gets a primary
and a secondary identity.

The Driver role is entity-backed: the acting X-User-ID must equal the id of the
Driver record being addressed. There is consequently no fixed Driver identity;
make_driver_headers(driver_id) builds the headers for whichever driver row the
test created.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

PAYROLL_ADMIN_ID = "admin-01"
PAYROLL_ADMIN_ALT_ID = "admin-02"
SETTLEMENT_CLERK_ID = "clerk-01"
SETTLEMENT_CLERK_ALT_ID = "clerk-02"
SETTLEMENT_APPROVER_ID = "approver-01"
SETTLEMENT_APPROVER_ALT_ID = "approver-02"
COMPLIANCE_AUDITOR_ID = "auditor-01"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "payroll_admin": {"user_id": PAYROLL_ADMIN_ID, "role": UserRole.PAYROLL_ADMIN},
    "payroll_admin_alt": {"user_id": PAYROLL_ADMIN_ALT_ID, "role": UserRole.PAYROLL_ADMIN},
    "settlement_clerk": {"user_id": SETTLEMENT_CLERK_ID, "role": UserRole.SETTLEMENT_CLERK},
    "settlement_clerk_alt": {
        "user_id": SETTLEMENT_CLERK_ALT_ID,
        "role": UserRole.SETTLEMENT_CLERK,
    },
    "settlement_approver": {
        "user_id": SETTLEMENT_APPROVER_ID,
        "role": UserRole.SETTLEMENT_APPROVER,
    },
    "settlement_approver_alt": {
        "user_id": SETTLEMENT_APPROVER_ALT_ID,
        "role": UserRole.SETTLEMENT_APPROVER,
    },
    "compliance_auditor": {
        "user_id": COMPLIANCE_AUDITOR_ID,
        "role": UserRole.COMPLIANCE_AUDITOR,
    },
}

ADMIN_HEADERS = build_user_headers(PAYROLL_ADMIN_ID, UserRole.PAYROLL_ADMIN)
ADMIN_ALT_HEADERS = build_user_headers(PAYROLL_ADMIN_ALT_ID, UserRole.PAYROLL_ADMIN)
CLERK_HEADERS = build_user_headers(SETTLEMENT_CLERK_ID, UserRole.SETTLEMENT_CLERK)
CLERK_ALT_HEADERS = build_user_headers(SETTLEMENT_CLERK_ALT_ID, UserRole.SETTLEMENT_CLERK)
APPROVER_HEADERS = build_user_headers(SETTLEMENT_APPROVER_ID, UserRole.SETTLEMENT_APPROVER)
APPROVER_ALT_HEADERS = build_user_headers(
    SETTLEMENT_APPROVER_ALT_ID, UserRole.SETTLEMENT_APPROVER
)
AUDITOR_HEADERS = build_user_headers(COMPLIANCE_AUDITOR_ID, UserRole.COMPLIANCE_AUDITOR)


def make_driver_headers(driver_id: str) -> Dict[str, str]:
    """Headers for the entity-backed Driver role acting as the given driver row."""
    return build_user_headers(driver_id, UserRole.DRIVER)


def headers_for(user_key: str) -> Dict[str, str]:
    """Headers for one of the named office identities in TEST_USERS."""
    user = TEST_USERS[user_key]
    return build_user_headers(user["user_id"], user["role"])
