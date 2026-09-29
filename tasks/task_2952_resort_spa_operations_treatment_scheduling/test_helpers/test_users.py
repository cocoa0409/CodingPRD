"""Role header builders for the five roles the PRD names.

PRD §2.1: "When `X-User-Role` is `Therapist`, `X-User-ID` is the `id` of the
acting `Therapist` entity ... When `X-User-Role` is `Guest`, `X-User-ID` is the
`id` of the acting `Guest` entity". Those two roles are therefore entity-backed
and any ownership-sensitive call MUST use make_therapist_headers(therapist_id) /
make_guest_headers(guest_id) with the real entity id.

"When `X-User-Role` is `SpaDirector`, `ComplianceOfficer` or `SpaCoordinator`,
`X-User-ID` is an opaque operator identifier that is not tied to any persisted
entity." Those three may use the shared constants, but licence review and intake
override compare two recorded operator ids against each other, so those flows
must pass DISTINCT user ids explicitly.
"""

from prd_bench_local_runner.testing import build_user_headers

# Default opaque operator identities.
DIRECTOR_USER_ID = "dir-1"
COMPLIANCE_USER_ID = "co-1"
COORDINATOR_USER_ID = "coord-1"

TEST_USERS = {
    "spa_director_headers": build_user_headers(DIRECTOR_USER_ID, "SpaDirector"),
    "compliance_officer_headers": build_user_headers(COMPLIANCE_USER_ID, "ComplianceOfficer"),
    "spa_coordinator_headers": build_user_headers(COORDINATOR_USER_ID, "SpaCoordinator"),
    # Entity-backed roles: placeholders only, safe exclusively for tests whose
    # outcome does not depend on ownership (for example role-authorisation and
    # authentication tests).
    "therapist_headers": build_user_headers("test-therapist-1", "Therapist"),
    "guest_headers": build_user_headers("test-guest-1", "Guest"),
}


def make_director_headers(user_id: str = DIRECTOR_USER_ID) -> dict:
    return build_user_headers(user_id, "SpaDirector")


def make_compliance_headers(user_id: str = COMPLIANCE_USER_ID) -> dict:
    """ComplianceOfficer. Pass DISTINCT ids for licence submit vs licence review
    and for intake screen vs director override counterparties."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_coordinator_headers(user_id: str = COORDINATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "SpaCoordinator")


def make_therapist_headers(therapist_id: str) -> dict:
    """Therapist is entity-backed: X-User-ID must be the Therapist.id."""
    return build_user_headers(therapist_id, "Therapist")


def make_guest_headers(guest_id: str) -> dict:
    """Guest is entity-backed: X-User-ID must be the Guest.id."""
    return build_user_headers(guest_id, "Guest")


def make_headers(role: str, user_id: str) -> dict:
    """Build headers for an arbitrary (possibly unrecognised) role string."""
    return build_user_headers(user_id, role)


def headers_missing_user_id(role: str = "SpaDirector") -> dict:
    """Headers whose X-User-ID is the empty string — PRD §2.1: "If either header
    is absent or empty". The value is exactly "" and never whitespace."""
    return {"X-User-ID": "", "X-User-Role": role}


def headers_missing_role(user_id: str = DIRECTOR_USER_ID) -> dict:
    """Headers whose X-User-Role is exactly the empty string."""
    return {"X-User-ID": user_id, "X-User-Role": ""}


def headers_absent_role(user_id: str = DIRECTOR_USER_ID) -> dict:
    """X-User-Role header entirely absent."""
    return {"X-User-ID": user_id}


def headers_absent_user_id(role: str = "SpaDirector") -> dict:
    """X-User-ID header entirely absent."""
    return {"X-User-Role": role}
