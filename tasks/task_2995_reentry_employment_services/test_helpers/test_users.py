"""
Pre-built caller identities for the Reentry Employment Services API.

The PRD requires every request except the logical-clock write to carry
`X-User-ID` and `X-User-Role`, so each role gets a ready-made header dict here.
Distinct operators inside the same role carry distinct `X-User-ID` values,
because several rules in the PRD — case-officer ownership, the segregation of
review from settlement — compare one caller's identifier against another's.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CASE_MANAGER,
    ROLE_EMPLOYER_LIAISON,
    ROLE_FUNDER_ANALYST,
    ROLE_PARTICIPANT,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_SUPERVISION_OFFICER,
)

# Operator identifiers.
CASE_MANAGER_ID = "cm-1"
CASE_MANAGER_2_ID = "cm-2"
EMPLOYER_LIAISON_ID = "liaison-1"
EMPLOYER_LIAISON_2_ID = "liaison-2"
PROGRAM_DIRECTOR_ID = "pd-1"
PROGRAM_DIRECTOR_2_ID = "pd-2"
SUPERVISION_OFFICER_ID = "officer-1"
SUPERVISION_OFFICER_2_ID = "officer-2"
FUNDER_ANALYST_ID = "analyst-1"
FUNDER_ANALYST_2_ID = "analyst-2"

CASE_MANAGER = build_user_headers(CASE_MANAGER_ID, ROLE_CASE_MANAGER)
CASE_MANAGER_2 = build_user_headers(CASE_MANAGER_2_ID, ROLE_CASE_MANAGER)
EMPLOYER_LIAISON = build_user_headers(EMPLOYER_LIAISON_ID, ROLE_EMPLOYER_LIAISON)
EMPLOYER_LIAISON_2 = build_user_headers(EMPLOYER_LIAISON_2_ID, ROLE_EMPLOYER_LIAISON)
PROGRAM_DIRECTOR = build_user_headers(PROGRAM_DIRECTOR_ID, ROLE_PROGRAM_DIRECTOR)
PROGRAM_DIRECTOR_2 = build_user_headers(PROGRAM_DIRECTOR_2_ID, ROLE_PROGRAM_DIRECTOR)
SUPERVISION_OFFICER = build_user_headers(
    SUPERVISION_OFFICER_ID, ROLE_SUPERVISION_OFFICER
)
SUPERVISION_OFFICER_2 = build_user_headers(
    SUPERVISION_OFFICER_2_ID, ROLE_SUPERVISION_OFFICER
)
FUNDER_ANALYST = build_user_headers(FUNDER_ANALYST_ID, ROLE_FUNDER_ANALYST)
FUNDER_ANALYST_2 = build_user_headers(FUNDER_ANALYST_2_ID, ROLE_FUNDER_ANALYST)

# The clock endpoint requires no authentication at all.
NO_AUTH = {"Content-Type": "application/json"}


def participant_headers(participant_id: str) -> dict:
    """
    Headers for a participant acting on their own record.

    Offer responses are ownership-checked against the placement's
    `participant_id`, so the caller's `X-User-ID` must be the participant's own
    resource id.
    """
    return build_user_headers(participant_id, ROLE_PARTICIPANT)


def headers_for_role(role: str, user_id: str) -> dict:
    """Headers for an arbitrary role/operator pair."""
    return build_user_headers(user_id, role)


def headers_with_empty_user_id(role: str) -> dict:
    """
    Headers whose `X-User-ID` is present but an empty string.

    The value must be the empty string exactly — a blank space is a different
    value and would not exercise the PRD's empty-identifier rule.
    """
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_without_user_id(role: str) -> dict:
    """Headers with `X-User-ID` omitted entirely."""
    return {
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


ROLE_HEADERS = {
    ROLE_CASE_MANAGER: CASE_MANAGER,
    ROLE_EMPLOYER_LIAISON: EMPLOYER_LIAISON,
    ROLE_PROGRAM_DIRECTOR: PROGRAM_DIRECTOR,
    ROLE_SUPERVISION_OFFICER: SUPERVISION_OFFICER,
    ROLE_FUNDER_ANALYST: FUNDER_ANALYST,
}
