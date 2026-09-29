"""Pre-built role headers for every role the PRD declares.

`Applicant` is the one role whose `X-User-ID` is the id of a persisted record —
the id returned by applicant registration. Every ownership-gated call therefore
has to use `make_applicant_headers(applicant["id"])`. The other six roles carry
opaque operator identifiers, so the shared constants below are the canonical
form for them.
"""

from prd_bench_local_runner.testing import build_user_headers

# Canonical operator identifiers used across the suite.
ADMIN_USER_ID = "admin-1"
INTAKE_USER_ID = "intake-1"
INTAKE_USER_ID_2 = "intake-2"
REVIEWER_USER_ID_1 = "rev-1"
REVIEWER_USER_ID_2 = "rev-2"
REVIEWER_USER_ID_3 = "rev-3"
OFFICER_USER_ID = "officer-1"
BOARD_USER_ID = "board-1"
PUBLIC_USER_ID = "public-1"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "program_admin_headers": build_user_headers(ADMIN_USER_ID, "ProgramAdmin"),
    "intake_analyst_headers": build_user_headers(INTAKE_USER_ID, "IntakeAnalyst"),
    "intake_analyst_2_headers": build_user_headers(INTAKE_USER_ID_2, "IntakeAnalyst"),
    "review_analyst_headers": build_user_headers(REVIEWER_USER_ID_1, "ReviewAnalyst"),
    "review_analyst_2_headers": build_user_headers(REVIEWER_USER_ID_2, "ReviewAnalyst"),
    "review_analyst_3_headers": build_user_headers(REVIEWER_USER_ID_3, "ReviewAnalyst"),
    "decision_officer_headers": build_user_headers(OFFICER_USER_ID, "DecisionOfficer"),
    "appeal_board_headers": build_user_headers(BOARD_USER_ID, "AppealBoardMember"),
    "public_participant_headers": build_user_headers(
        PUBLIC_USER_ID, "PublicParticipant"
    ),
    # Applicant identity is entity-backed; this constant is a fallback for
    # tests that never reach an ownership comparison (role or body-shape
    # rejections, and unknown-identifier reads).
    "applicant_headers": build_user_headers("unregistered-applicant", "Applicant"),
}


def make_applicant_headers(applicant_id: str) -> dict:
    """Headers for the `Applicant` role.

    `X-User-ID` must be the id of the acting applicant record, so pass the id
    returned by applicant registration whenever the call is ownership-gated.
    """
    return build_user_headers(applicant_id, "Applicant")


def make_program_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_intake_analyst_headers(user_id: str = INTAKE_USER_ID) -> dict:
    return build_user_headers(user_id, "IntakeAnalyst")


def make_review_analyst_headers(user_id: str = REVIEWER_USER_ID_1) -> dict:
    return build_user_headers(user_id, "ReviewAnalyst")


def make_decision_officer_headers(user_id: str = OFFICER_USER_ID) -> dict:
    return build_user_headers(user_id, "DecisionOfficer")


def make_appeal_board_headers(user_id: str = BOARD_USER_ID) -> dict:
    return build_user_headers(user_id, "AppealBoardMember")


def make_public_participant_headers(user_id: str = PUBLIC_USER_ID) -> dict:
    return build_user_headers(user_id, "PublicParticipant")


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary user id / role pair, for role-admissibility scenarios."""
    return build_user_headers(user_id, role)
