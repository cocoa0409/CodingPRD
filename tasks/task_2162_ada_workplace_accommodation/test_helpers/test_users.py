"""Pre-built role headers for the seven roles the PRD declares.

Five roles carry opaque identity: ``AccommodationCoordinator``,
``MedicalReviewOfficer``, ``FinanceOfficer``, ``AppealOfficer`` and
``ComplianceAuditor``.  Their ``X-User-ID`` is an operator token that the
server records where an audit trail is demanded but never compares against a
row's ``id``, so a shared constant is the canonical form.

Two roles are entity-backed: ``Employee`` and ``Manager`` both carry the
``id`` of an acting ``Employee`` row.  Every ownership-gated or
department-scoped call for those two MUST be built with the per-instance
builders below, passing the real employee id.
"""

from prd_bench_local_runner.testing import build_user_headers

COORDINATOR_USER_ID = "COORD-1"
SECOND_COORDINATOR_USER_ID = "COORD-2"
MEDICAL_OFFICER_USER_ID = "MRO-1"
FINANCE_USER_ID = "FIN-1"
APPEAL_OFFICER_USER_ID = "APPEAL-1"
SECOND_APPEAL_OFFICER_USER_ID = "APPEAL-7"
AUDITOR_USER_ID = "AUD-1"

TEST_USERS = {
    "coordinator_headers": build_user_headers(
        COORDINATOR_USER_ID, "AccommodationCoordinator"
    ),
    "second_coordinator_headers": build_user_headers(
        SECOND_COORDINATOR_USER_ID, "AccommodationCoordinator"
    ),
    "medical_officer_headers": build_user_headers(
        MEDICAL_OFFICER_USER_ID, "MedicalReviewOfficer"
    ),
    "finance_headers": build_user_headers(FINANCE_USER_ID, "FinanceOfficer"),
    "appeal_officer_headers": build_user_headers(
        APPEAL_OFFICER_USER_ID, "AppealOfficer"
    ),
    "second_appeal_officer_headers": build_user_headers(
        SECOND_APPEAL_OFFICER_USER_ID, "AppealOfficer"
    ),
    "auditor_headers": build_user_headers(AUDITOR_USER_ID, "ComplianceAuditor"),
    # Placeholders only.  Any Employee or Manager call that touches an
    # ownership or department-scope check must use the builders below.
    "employee_headers": build_user_headers("employee-unbound", "Employee"),
    "manager_headers": build_user_headers("manager-unbound", "Manager"),
}


def make_employee_headers(employee_id: str) -> dict:
    """Headers for the Employee whose own row id is given."""
    return build_user_headers(employee_id, "Employee")


def make_manager_headers(employee_id: str) -> dict:
    """Headers for a Manager, carrying the acting Employee row's own id."""
    return build_user_headers(employee_id, "Manager")


def make_coordinator_headers(user_id: str) -> dict:
    """Headers for a named AccommodationCoordinator operator identity."""
    return build_user_headers(user_id, "AccommodationCoordinator")


def make_appeal_officer_headers(user_id: str) -> dict:
    """Headers for a named AppealOfficer operator identity."""
    return build_user_headers(user_id, "AppealOfficer")


def make_finance_headers(user_id: str) -> dict:
    """Headers for a named FinanceOfficer operator identity."""
    return build_user_headers(user_id, "FinanceOfficer")


def make_headers_with_unknown_role(user_id: str = "someone") -> dict:
    """Headers naming a role outside the seven the PRD declares."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "Paralegal",
        "Content-Type": "application/json",
    }


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
