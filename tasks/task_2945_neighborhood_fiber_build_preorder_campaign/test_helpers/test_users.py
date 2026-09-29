"""Pre-built role headers for every role the PRD declares.

Six roles carry opaque identity: their `X-User-ID` is an operator identifier
that is not tied to any persisted entity. Two roles — `Subscriber` and
`MduOwner` — are account-backed: their `X-User-ID` must be the id of the
`Account` row they act for, so every ownership-gated call uses the per-instance
builder rather than a shared constant.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# --- Opaque operator identifiers ---------------------------------------------
# Distinct identifiers matter for the claim workflow: the operator deciding a
# claim must differ from the operator who assessed it.
PROGRAM_MANAGER_USER_ID = "u-program-manager-1"
PERMIT_OFFICE_USER_ID = "u-permit-office-1"
UTILITY_OPERATOR_USER_ID = "u-utility-operator-1"
INSTALL_COORDINATOR_USER_ID = "u-install-coordinator-1"
CLAIMS_ASSESSOR_USER_ID = "u-assessor-1"
CLAIMS_ASSESSOR_2_USER_ID = "u-assessor-2"
CLAIMS_APPROVER_USER_ID = "u-approver-1"
CLAIMS_APPROVER_2_USER_ID = "u-approver-2"

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles: the shared constant is the canonical form.
    "program_manager_headers": build_user_headers(
        PROGRAM_MANAGER_USER_ID, "ProgramManager"
    ),
    "permit_office_headers": build_user_headers(PERMIT_OFFICE_USER_ID, "PermitOffice"),
    "utility_operator_headers": build_user_headers(
        UTILITY_OPERATOR_USER_ID, "UtilityOperator"
    ),
    "install_coordinator_headers": build_user_headers(
        INSTALL_COORDINATOR_USER_ID, "InstallCoordinator"
    ),
    "claims_assessor_headers": build_user_headers(
        CLAIMS_ASSESSOR_USER_ID, "ClaimsAssessor"
    ),
    "claims_assessor_2_headers": build_user_headers(
        CLAIMS_ASSESSOR_2_USER_ID, "ClaimsAssessor"
    ),
    "claims_approver_headers": build_user_headers(
        CLAIMS_APPROVER_USER_ID, "ClaimsApprover"
    ),
    "claims_approver_2_headers": build_user_headers(
        CLAIMS_APPROVER_2_USER_ID, "ClaimsApprover"
    ),
    # Account-backed roles: these shared constants are a fallback for tests that
    # do not exercise ownership at all (role-refusal and unknown-id tests).
    "subscriber_headers": build_user_headers("u-subscriber-unbound", "Subscriber"),
    "mdu_owner_headers": build_user_headers("u-mdu-owner-unbound", "MduOwner"),
}


# --- Per-instance builders ---------------------------------------------------
def make_subscriber_headers(account_id: str) -> Dict[str, str]:
    """Headers for `Subscriber`, whose `X-User-ID` is the acting `Account.id`."""
    return build_user_headers(account_id, "Subscriber")


def make_mdu_owner_headers(account_id: str) -> Dict[str, str]:
    """Headers for `MduOwner`, whose `X-User-ID` is the owning `Account.id`."""
    return build_user_headers(account_id, "MduOwner")


def make_program_manager_headers(
    user_id: str = PROGRAM_MANAGER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, "ProgramManager")


def make_permit_office_headers(user_id: str = PERMIT_OFFICE_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "PermitOffice")


def make_utility_operator_headers(
    user_id: str = UTILITY_OPERATOR_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, "UtilityOperator")


def make_install_coordinator_headers(
    user_id: str = INSTALL_COORDINATOR_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, "InstallCoordinator")


def make_claims_assessor_headers(
    user_id: str = CLAIMS_ASSESSOR_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, "ClaimsAssessor")


def make_claims_approver_headers(
    user_id: str = CLAIMS_APPROVER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, "ClaimsApprover")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary identifier/role pair, for role-refusal probes."""
    return build_user_headers(user_id, role)


def missing_role_headers(user_id: str = PROGRAM_MANAGER_USER_ID) -> Dict[str, str]:
    """Headers with no `X-User-Role` at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def missing_user_id_headers(role: str = "ProgramManager") -> Dict[str, str]:
    """Headers with no `X-User-ID` at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def blank_role_headers(user_id: str = PROGRAM_MANAGER_USER_ID) -> Dict[str, str]:
    """Headers whose `X-User-Role` is the empty string.

    The value is `""` and never whitespace: a spaces-only header value is
    rejected by the HTTP client before it ever reaches the server.
    """
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def blank_user_id_headers(role: str = "ProgramManager") -> Dict[str, str]:
    """Headers whose `X-User-ID` is the empty string."""
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

UNKNOWN_ROLE_HEADERS: Dict[str, str] = build_user_headers(
    "u-super-admin-1", "SuperAdmin"
)
