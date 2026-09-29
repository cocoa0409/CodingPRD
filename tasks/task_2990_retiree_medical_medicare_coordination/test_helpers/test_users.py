"""Pre-built auth headers for every role in the PRD.

PRD 2.1: seven operator roles are opaque, so any stable X-User-ID is accepted
for them. The eighth role, Retiree, is entity-backed — its X-User-ID is the id
of the Retiree row it acts for, and a mismatch is an authorization failure.
Every ownership-gated Retiree call therefore MUST use
make_retiree_headers(retiree_id) with the real Retiree id.

PRD 2.7 makes segregation of duties observable, so the operator roles come in
distinct numbered identities: the user that creates or attests a record must be
able to differ from the user that certifies, decides or settles it.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ACTUARY,
    ROLE_BENEFITS_ADMIN,
    ROLE_BILLING_CLERK,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_ELIGIBILITY_ANALYST,
    ROLE_ENROLLMENT_COUNSELOR,
    ROLE_HRA_ADMINISTRATOR,
    ROLE_RETIREE,
)

# Canonical user ids. Two ids exist for every role that sits on one of the six
# segregation-of-duties pairings in PRD 2.7.
ADMIN_1 = "admin-01"
ADMIN_2 = "admin-02"
ANALYST_1 = "analyst-01"
ANALYST_2 = "analyst-02"
ANALYST_3 = "analyst-03"
COUNSELOR_1 = "counselor-01"
COUNSELOR_2 = "counselor-02"
COUNSELOR_3 = "counselor-03"
HRA_ADMIN_1 = "hra-admin-01"
HRA_ADMIN_2 = "hra-admin-02"
BILLING_1 = "billing-01"
BILLING_2 = "billing-02"
ACTUARY_1 = "actuary-01"
ACTUARY_2 = "actuary-02"
COMPLIANCE_1 = "compliance-01"
COMPLIANCE_2 = "compliance-02"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "benefits_admin_headers": build_user_headers(ADMIN_1, ROLE_BENEFITS_ADMIN),
    "benefits_admin_2_headers": build_user_headers(ADMIN_2, ROLE_BENEFITS_ADMIN),
    "eligibility_analyst_headers": build_user_headers(ANALYST_1, ROLE_ELIGIBILITY_ANALYST),
    "eligibility_analyst_2_headers": build_user_headers(
        ANALYST_2, ROLE_ELIGIBILITY_ANALYST
    ),
    "eligibility_analyst_3_headers": build_user_headers(
        ANALYST_3, ROLE_ELIGIBILITY_ANALYST
    ),
    "enrollment_counselor_headers": build_user_headers(
        COUNSELOR_1, ROLE_ENROLLMENT_COUNSELOR
    ),
    "enrollment_counselor_2_headers": build_user_headers(
        COUNSELOR_2, ROLE_ENROLLMENT_COUNSELOR
    ),
    "enrollment_counselor_3_headers": build_user_headers(
        COUNSELOR_3, ROLE_ENROLLMENT_COUNSELOR
    ),
    "hra_administrator_headers": build_user_headers(HRA_ADMIN_1, ROLE_HRA_ADMINISTRATOR),
    "hra_administrator_2_headers": build_user_headers(
        HRA_ADMIN_2, ROLE_HRA_ADMINISTRATOR
    ),
    "billing_clerk_headers": build_user_headers(BILLING_1, ROLE_BILLING_CLERK),
    "billing_clerk_2_headers": build_user_headers(BILLING_2, ROLE_BILLING_CLERK),
    "actuary_headers": build_user_headers(ACTUARY_1, ROLE_ACTUARY),
    "actuary_2_headers": build_user_headers(ACTUARY_2, ROLE_ACTUARY),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_1, ROLE_COMPLIANCE_OFFICER
    ),
    "compliance_officer_2_headers": build_user_headers(
        COMPLIANCE_2, ROLE_COMPLIANCE_OFFICER
    ),
    # Entity-backed role: this placeholder id belongs to no Retiree row, so it
    # is only safe where the expected outcome does not depend on ownership
    # (for example a role-authorization rejection that happens first).
    "retiree_headers": build_user_headers("00000000-0000-0000-0000-0000000000ff", ROLE_RETIREE),
}


def make_benefits_admin_headers(user_id: str = ADMIN_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_BENEFITS_ADMIN)


def make_eligibility_analyst_headers(user_id: str = ANALYST_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_ELIGIBILITY_ANALYST)


def make_enrollment_counselor_headers(user_id: str = COUNSELOR_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_ENROLLMENT_COUNSELOR)


def make_hra_administrator_headers(user_id: str = HRA_ADMIN_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_HRA_ADMINISTRATOR)


def make_billing_clerk_headers(user_id: str = BILLING_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_BILLING_CLERK)


def make_actuary_headers(user_id: str = ACTUARY_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_ACTUARY)


def make_compliance_officer_headers(user_id: str = COMPLIANCE_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_retiree_headers(retiree_id: str) -> Dict[str, str]:
    """Headers for the entity-backed Retiree role.

    PRD 2.1: for Retiree the X-User-ID header is the id of the Retiree row the
    caller acts for, so pass the real Retiree id on every ownership-gated call
    (claim submission, premium payment, own-record reads).
    """
    return build_user_headers(retiree_id, ROLE_RETIREE)


def make_headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Build headers for an arbitrary (role, user_id) pair."""
    return build_user_headers(user_id, role)


__all__ = [
    "TEST_USERS",
    "ADMIN_1",
    "ADMIN_2",
    "ANALYST_1",
    "ANALYST_2",
    "ANALYST_3",
    "COUNSELOR_1",
    "COUNSELOR_2",
    "COUNSELOR_3",
    "HRA_ADMIN_1",
    "HRA_ADMIN_2",
    "BILLING_1",
    "BILLING_2",
    "ACTUARY_1",
    "ACTUARY_2",
    "COMPLIANCE_1",
    "COMPLIANCE_2",
    "make_benefits_admin_headers",
    "make_eligibility_analyst_headers",
    "make_enrollment_counselor_headers",
    "make_hra_administrator_headers",
    "make_billing_clerk_headers",
    "make_actuary_headers",
    "make_compliance_officer_headers",
    "make_retiree_headers",
    "make_headers_for_role",
]
