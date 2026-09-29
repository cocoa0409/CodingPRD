"""Pre-built role headers for every role in PRD §2.1.

`Interpreter` is the only entity-backed role: its `X-User-ID` must equal the
`Interpreter` row's `id`, so ownership-gated calls MUST use
make_interpreter_headers(interpreter["id"]). The other five roles are opaque
operator identifiers that the program merely records.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers (PRD §2.1). Distinct ids per role instance so that
# segregation-of-duties scenarios have genuinely different actors to work with.
PROGRAM_ADMIN_USER_ID = "pa-001"
PROGRAM_ADMIN_ALT_USER_ID = "pa-002"
CREDENTIALING_OFFICER_USER_ID = "co-001"
SCHEDULING_COORDINATOR_USER_ID = "sc-001"
FISCAL_OFFICER_USER_ID = "fo-001"
FISCAL_OFFICER_ALT_USER_ID = "fo-002"
QUALITY_REVIEWER_USER_ID = "qr-001"
QUALITY_REVIEWER_ALT_USER_ID = "qr-002"
QUALITY_REVIEWER_THIRD_USER_ID = "qr-003"

TEST_USERS = {
    "program_admin_headers": build_user_headers(PROGRAM_ADMIN_USER_ID, "ProgramAdmin"),
    "program_admin_alt_headers": build_user_headers(
        PROGRAM_ADMIN_ALT_USER_ID, "ProgramAdmin"
    ),
    "credentialing_officer_headers": build_user_headers(
        CREDENTIALING_OFFICER_USER_ID, "CredentialingOfficer"
    ),
    "scheduling_coordinator_headers": build_user_headers(
        SCHEDULING_COORDINATOR_USER_ID, "SchedulingCoordinator"
    ),
    "fiscal_officer_headers": build_user_headers(FISCAL_OFFICER_USER_ID, "FiscalOfficer"),
    "fiscal_officer_alt_headers": build_user_headers(
        FISCAL_OFFICER_ALT_USER_ID, "FiscalOfficer"
    ),
    "quality_reviewer_headers": build_user_headers(
        QUALITY_REVIEWER_USER_ID, "QualityReviewer"
    ),
    "quality_reviewer_alt_headers": build_user_headers(
        QUALITY_REVIEWER_ALT_USER_ID, "QualityReviewer"
    ),
    "quality_reviewer_third_headers": build_user_headers(
        QUALITY_REVIEWER_THIRD_USER_ID, "QualityReviewer"
    ),
    # Fallback only — never use for an ownership-gated Interpreter call.
    "interpreter_headers": build_user_headers("test-interpreter-1", "Interpreter"),
}


def make_interpreter_headers(user_id: str) -> dict:
    """Headers for the Interpreter role (entity_backed:Interpreter).

    Pass the actual Interpreter row's `id` whenever the call is ownership-gated
    (confirm, decline, check-in, complete, pay-claim submit, complaint appeal).
    """
    return build_user_headers(user_id, "Interpreter")


def make_program_admin_headers(user_id: str) -> dict:
    """ProgramAdmin headers with an explicit operator id (opaque identity)."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_quality_reviewer_headers(user_id: str) -> dict:
    """QualityReviewer headers with an explicit operator id (opaque identity)."""
    return build_user_headers(user_id, "QualityReviewer")


def make_scheduling_coordinator_headers(user_id: str) -> dict:
    """SchedulingCoordinator headers with an explicit operator id."""
    return build_user_headers(user_id, "SchedulingCoordinator")


def make_credentialing_officer_headers(user_id: str) -> dict:
    """CredentialingOfficer headers with an explicit operator id."""
    return build_user_headers(user_id, "CredentialingOfficer")


def make_fiscal_officer_headers(user_id: str) -> dict:
    """FiscalOfficer headers with an explicit operator id."""
    return build_user_headers(user_id, "FiscalOfficer")


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary (user_id, role) pair — for RBAC and authentication probes."""
    return build_user_headers(user_id, role)
