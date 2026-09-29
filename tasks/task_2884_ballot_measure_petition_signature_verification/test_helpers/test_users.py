"""Pre-built role headers for every role in the specification.

`X-User-ID` binds to data differently per role. For `CountyClerk` it is the
acting `County.id`; for `CirculatorAgent` it is the acting `Circulator.id`. For
`SosAdmin`, `ElectionsExaminer`, `TitleExaminer`, `Proponent` and `Challenger`
it is an opaque operator identifier not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used consistently across fixtures and tests.
ADMIN_USER_ID = "admin-1"
EXAMINER_USER_ID = "exam-1"
SECOND_EXAMINER_USER_ID = "exam-2"
THIRD_EXAMINER_USER_ID = "exam-3"
TITLE_USER_ID = "title-1"
PROPONENT_USER_ID = "prop-1"
OTHER_PROPONENT_USER_ID = "prop-2"
CHALLENGER_USER_ID = "chal-1"
OTHER_CHALLENGER_USER_ID = "chal-2"

# Shared constants. Safe for opaque roles, and for tests that do not exercise
# an entity-backed ownership comparison.
TEST_USERS = {
    "sos_admin_headers": build_user_headers(ADMIN_USER_ID, "SosAdmin"),
    "elections_examiner_headers": build_user_headers(EXAMINER_USER_ID, "ElectionsExaminer"),
    "second_examiner_headers": build_user_headers(SECOND_EXAMINER_USER_ID, "ElectionsExaminer"),
    "third_examiner_headers": build_user_headers(THIRD_EXAMINER_USER_ID, "ElectionsExaminer"),
    "title_examiner_headers": build_user_headers(TITLE_USER_ID, "TitleExaminer"),
    "proponent_headers": build_user_headers(PROPONENT_USER_ID, "Proponent"),
    "other_proponent_headers": build_user_headers(OTHER_PROPONENT_USER_ID, "Proponent"),
    "challenger_headers": build_user_headers(CHALLENGER_USER_ID, "Challenger"),
    "other_challenger_headers": build_user_headers(OTHER_CHALLENGER_USER_ID, "Challenger"),
    # entity_backed roles: these shared constants never equal a real entity id,
    # so they are only for tests that stop before the ownership comparison.
    "county_clerk_headers": build_user_headers("clerk-not-a-county", "CountyClerk"),
    "circulator_agent_headers": build_user_headers("agent-not-a-circulator", "CirculatorAgent"),
}


# --- Per-instance builders -------------------------------------------------

def make_sos_admin_headers(user_id=ADMIN_USER_ID):
    return build_user_headers(user_id, "SosAdmin")


def make_examiner_headers(user_id=EXAMINER_USER_ID):
    return build_user_headers(user_id, "ElectionsExaminer")


def make_title_examiner_headers(user_id=TITLE_USER_ID):
    return build_user_headers(user_id, "TitleExaminer")


def make_proponent_headers(user_id=PROPONENT_USER_ID):
    """A Proponent may act on a Petition only when the petition's
    proponent_user_id equals X-User-ID."""
    return build_user_headers(user_id, "Proponent")


def make_challenger_headers(user_id=CHALLENGER_USER_ID):
    """A Challenger may escalate a Challenge only when that challenge's
    challenger_user_id equals X-User-ID."""
    return build_user_headers(user_id, "Challenger")


def make_county_clerk_headers(county_id):
    """For CountyClerk. Pass the acting County's id as X-User-ID; every
    ownership check compares the resource's county foreign key against it."""
    return build_user_headers(county_id, "CountyClerk")


def make_circulator_agent_headers(circulator_id):
    """For CirculatorAgent. Pass the acting Circulator's id as X-User-ID."""
    return build_user_headers(circulator_id, "CirculatorAgent")


def make_headers(user_id, role):
    """Free-form builder for role-matrix parametrisation."""
    return build_user_headers(user_id, role)
