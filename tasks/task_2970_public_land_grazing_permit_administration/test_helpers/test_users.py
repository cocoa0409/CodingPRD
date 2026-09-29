"""Pre-built role headers.

PRD 2.1: for `RangeSpecialist`, `AuthorizedOfficer`, `AppealsAdjudicator` and
`SystemAdmin` the `X-User-ID` is an opaque operator identifier not tied to any
persisted entity, so shared constants are safe. `Permittee` is entity-backed —
`X-User-ID` is the id of the acting `Permittee` record itself — so ownership
gated calls MUST use make_permittee_headers(permittee["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers (PRD 2.1). Distinct ids are needed because the
# segregation-of-duties rules of PRD 2.10 compare identifiers, never roles.
OFFICER_1 = "u_officer_1"
OFFICER_2 = "u_officer_2"
SPECIALIST_1 = "u_spec_1"
SPECIALIST_2 = "u_spec_2"
JUDGE_1 = "u_judge_1"
JUDGE_2 = "u_judge_2"
ADMIN_1 = "u_admin_1"

TEST_USERS = {
    "officer_headers": build_user_headers(OFFICER_1, "AuthorizedOfficer"),
    "officer_2_headers": build_user_headers(OFFICER_2, "AuthorizedOfficer"),
    "specialist_headers": build_user_headers(SPECIALIST_1, "RangeSpecialist"),
    "specialist_2_headers": build_user_headers(SPECIALIST_2, "RangeSpecialist"),
    "adjudicator_headers": build_user_headers(JUDGE_1, "AppealsAdjudicator"),
    "adjudicator_2_headers": build_user_headers(JUDGE_2, "AppealsAdjudicator"),
    "system_admin_headers": build_user_headers(ADMIN_1, "SystemAdmin"),
    # Entity-backed role: placeholder only, for tests whose outcome does not
    # depend on ownership (e.g. an unknown-actor rejection).
    "permittee_headers": build_user_headers("u_unknown_permittee", "Permittee"),
}


def make_officer_headers(user_id: str = OFFICER_1) -> dict:
    return build_user_headers(user_id, "AuthorizedOfficer")


def make_specialist_headers(user_id: str = SPECIALIST_1) -> dict:
    return build_user_headers(user_id, "RangeSpecialist")


def make_adjudicator_headers(user_id: str = JUDGE_1) -> dict:
    return build_user_headers(user_id, "AppealsAdjudicator")


def make_system_admin_headers(user_id: str = ADMIN_1) -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_permittee_headers(permittee_id: str) -> dict:
    """For the entity-backed `Permittee` role: pass the acting Permittee.id."""
    return build_user_headers(permittee_id, "Permittee")


def headers_for_role(role: str, user_id: str) -> dict:
    """Arbitrary role/identifier pairing, for role-gate tests."""
    return build_user_headers(user_id, role)
