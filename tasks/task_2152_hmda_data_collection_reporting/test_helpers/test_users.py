"""Pre-built role headers for every role in the PRD."""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Five of the six roles carry an opaque operator identifier
# that the server never compares to any entity id, so a shared constant is the
# canonical form for them. InstitutionAdmin's identifier IS an Institution id,
# so its shared constant is only safe for tests that never reach the scope check
# successfully (for example the deliberate scope-violation case).
TEST_USERS = {
    "system_admin_headers": build_user_headers("test-system-admin-1", "SystemAdmin"),
    "institution_admin_headers": build_user_headers(
        "test-institution-admin-1", "InstitutionAdmin"
    ),
    "loan_officer_headers": build_user_headers("test-loan-officer-1", "LoanOfficer"),
    "compliance_analyst_headers": build_user_headers(
        "analyst-nova", "ComplianceAnalyst"
    ),
    "compliance_officer_headers": build_user_headers(
        "officer-alpha", "ComplianceOfficer"
    ),
    "examiner_headers": build_user_headers("examiner-rho", "Examiner"),
}


def make_system_admin_headers(user_id: str = "test-system-admin-1") -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_institution_admin_headers(user_id: str) -> dict:
    """InstitutionAdmin is backed by an Institution row: pass that Institution's
    id as user_id whenever the call must pass the institution scope check."""
    return build_user_headers(user_id, "InstitutionAdmin")


def make_loan_officer_headers(user_id: str = "test-loan-officer-1") -> dict:
    return build_user_headers(user_id, "LoanOfficer")


def make_compliance_analyst_headers(user_id: str = "analyst-nova") -> dict:
    """The analyst identifier is stored on a verified exception as
    verified_by_user_id, so tests that exercise segregation of duties must
    control it explicitly."""
    return build_user_headers(user_id, "ComplianceAnalyst")


def make_compliance_officer_headers(user_id: str = "officer-alpha") -> dict:
    """The officer identifier is stored on certification as
    certified_by_user_id and compared against verified_by_user_id."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_examiner_headers(user_id: str = "examiner-rho") -> dict:
    return build_user_headers(user_id, "Examiner")


def no_auth_headers() -> dict:
    """A request carrying neither X-User-ID nor X-User-Role."""
    return {"Content-Type": "application/json"}
