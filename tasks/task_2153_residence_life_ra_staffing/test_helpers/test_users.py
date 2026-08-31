"""Pre-built role headers for every role the PRD declares.

Two roles are backed by a persisted entity: a `ResidentAssistant` caller's
`X-User-ID` is the acting RA record's `id` and a `Student` caller's is the
acting Student record's `id`.  Any ownership-gated call therefore MUST use the
per-instance builder with the real entity id — never the shared constant.
The remaining three roles carry opaque identities, for which the shared
constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

DIRECTOR_USER_ID = "rd-1"
CONDUCT_OFFICER_ONE_ID = "co-1"
CONDUCT_OFFICER_TWO_ID = "co-2"
BURSAR_USER_ID = "bo-1"

TEST_USERS = {
    # Opaque identities — the shared constant is the canonical form.
    "director_headers": build_user_headers(DIRECTOR_USER_ID, "ResidenceDirector"),
    "conduct_officer_headers": build_user_headers(
        CONDUCT_OFFICER_ONE_ID, "ConductOfficer"
    ),
    "second_conduct_officer_headers": build_user_headers(
        CONDUCT_OFFICER_TWO_ID, "ConductOfficer"
    ),
    "bursar_headers": build_user_headers(BURSAR_USER_ID, "BursarOfficer"),
    # Entity-backed identities — fallbacks for tests that never touch ownership.
    "ra_headers": build_user_headers("test-ra-1", "ResidentAssistant"),
    "student_headers": build_user_headers("test-student-1", "Student"),
}


def make_director_headers(user_id: str = DIRECTOR_USER_ID) -> dict:
    """Opaque operator identity for a ResidenceDirector."""
    return build_user_headers(user_id, "ResidenceDirector")


def make_conduct_officer_headers(user_id: str = CONDUCT_OFFICER_ONE_ID) -> dict:
    """Opaque operator identity for a ConductOfficer.

    The scheduling officer and the deciding officer must differ, so tests pass
    distinct identifiers here.
    """
    return build_user_headers(user_id, "ConductOfficer")


def make_bursar_headers(user_id: str = BURSAR_USER_ID) -> dict:
    """Opaque operator identity for a BursarOfficer."""
    return build_user_headers(user_id, "BursarOfficer")


def make_ra_headers(ra_id: str) -> dict:
    """For a ResidentAssistant caller — pass the acting RA record's own id."""
    return build_user_headers(ra_id, "ResidentAssistant")


def make_student_headers(student_id: str) -> dict:
    """For a Student caller — pass the acting Student record's own id."""
    return build_user_headers(student_id, "Student")


def headers_without_user_id(role: str = "ResidenceDirector") -> dict:
    """Headers carrying only X-User-Role, for the missing-header refusal path."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = DIRECTOR_USER_ID) -> dict:
    """Headers carrying only X-User-ID, for the missing-header refusal path."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
