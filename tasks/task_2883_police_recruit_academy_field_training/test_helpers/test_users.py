"""Acting identities and header builders.

Five of the eight roles are opaque: their ``X-User-ID`` is never compared
against a stored foreign key, so a stable literal is enough.  Three roles are
entity backed -- ``AcademyInstructor`` and ``FieldTrainingOfficer`` are
identified by an ``Instructor.id`` and ``Recruit`` by a ``Recruit.id`` -- so
their headers must be built from the identifier of the row that owns the
resource under test.

Two distinct identities exist for every role that participates in a
segregation-of-duties comparison, because the user who records findings may
never be the user who adjudicates them, and the user who approves a lesson plan
may never be the authoring instructor's user.  Never reuse one identifier for
two owners the contract requires to be distinct.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --- opaque identities -------------------------------------------------------
DIRECTOR_USER_ID = "dir-1"
DIRECTOR_ALT_USER_ID = "dir-2"

COORDINATOR_USER_ID = "tc-1"
COORDINATOR_ALT_USER_ID = "tc-2"

INVESTIGATOR_USER_ID = "bi-1"
INVESTIGATOR_ALT_USER_ID = "bi-2"

EXAMINER_USER_ID = "me-1"
EXAMINER_ALT_USER_ID = "me-2"

CUSTODIAN_USER_ID = "rc-1"

UNKNOWN_ROLE = "PoliceChief"


def director_headers(user_id: str = DIRECTOR_USER_ID):
    return build_user_headers(user_id, UserRole.ACADEMY_DIRECTOR.value)


def director_alt_headers():
    return build_user_headers(DIRECTOR_ALT_USER_ID, UserRole.ACADEMY_DIRECTOR.value)


def coordinator_headers(user_id: str = COORDINATOR_USER_ID):
    return build_user_headers(user_id, UserRole.TRAINING_COORDINATOR.value)


def coordinator_alt_headers():
    return build_user_headers(COORDINATOR_ALT_USER_ID, UserRole.TRAINING_COORDINATOR.value)


def investigator_headers(user_id: str = INVESTIGATOR_USER_ID):
    return build_user_headers(user_id, UserRole.BACKGROUND_INVESTIGATOR.value)


def investigator_alt_headers():
    return build_user_headers(INVESTIGATOR_ALT_USER_ID,
                              UserRole.BACKGROUND_INVESTIGATOR.value)


def examiner_headers(user_id: str = EXAMINER_USER_ID):
    return build_user_headers(user_id, UserRole.MEDICAL_EXAMINER.value)


def examiner_alt_headers():
    return build_user_headers(EXAMINER_ALT_USER_ID, UserRole.MEDICAL_EXAMINER.value)


def custodian_headers(user_id: str = CUSTODIAN_USER_ID):
    return build_user_headers(user_id, UserRole.RECORDS_CUSTODIAN.value)


# --- entity backed identities ------------------------------------------------
def make_academy_instructor_headers(instructor_id: str):
    """Act as the AcademyInstructor whose identity is this Instructor row."""
    return build_user_headers(instructor_id, UserRole.ACADEMY_INSTRUCTOR.value)


def make_fto_headers(instructor_id: str):
    """Act as the FieldTrainingOfficer whose identity is this Instructor row."""
    return build_user_headers(instructor_id, UserRole.FIELD_TRAINING_OFFICER.value)


def make_recruit_headers(recruit_id: str):
    """Act as the Recruit whose identity is this Recruit row."""
    return build_user_headers(recruit_id, UserRole.RECRUIT.value)


# --- malformed / unknown identities -----------------------------------------
def headers_for_role(role: str, user_id: str = "actor-1"):
    """Headers for an arbitrary role name, used to probe role authorization."""
    return build_user_headers(user_id, role)


def headers_missing_role(user_id: str = DIRECTOR_USER_ID):
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_missing_user_id(role: str = UserRole.ACADEMY_DIRECTOR.value):
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_empty_role(user_id: str = DIRECTOR_USER_ID):
    # The empty string, never a whitespace string: a blank header value must
    # actually reach the server rather than being rejected client side.
    return {"X-User-ID": user_id, "X-User-Role": "",
            "Content-Type": "application/json"}


def headers_empty_user_id(role: str = UserRole.ACADEMY_DIRECTOR.value):
    return {"X-User-ID": "", "X-User-Role": role,
            "Content-Type": "application/json"}


def headers_unknown_role(user_id: str = DIRECTOR_USER_ID):
    return build_user_headers(user_id, UNKNOWN_ROLE)


# Convenience map from role name to a ready-made header set for the five
# opaque roles; entity backed roles are absent because they need an id.
OPAQUE_ROLE_HEADERS = {
    UserRole.ACADEMY_DIRECTOR.value: director_headers,
    UserRole.TRAINING_COORDINATOR.value: coordinator_headers,
    UserRole.BACKGROUND_INVESTIGATOR.value: investigator_headers,
    UserRole.MEDICAL_EXAMINER.value: examiner_headers,
    UserRole.RECORDS_CUSTODIAN.value: custodian_headers,
}

# The role authorized to record findings for each screening type, and the role
# authorized to adjudicate them, per the subject-scoped screening authority.
SCREENING_AUTHORITY = {
    "BACKGROUND": (UserRole.BACKGROUND_INVESTIGATOR.value,
                   INVESTIGATOR_USER_ID, INVESTIGATOR_ALT_USER_ID),
    "MEDICAL": (UserRole.MEDICAL_EXAMINER.value,
                EXAMINER_USER_ID, EXAMINER_ALT_USER_ID),
    "PSYCHOLOGICAL": (UserRole.MEDICAL_EXAMINER.value,
                      EXAMINER_USER_ID, EXAMINER_ALT_USER_ID),
    "PHYSICAL_FITNESS": (UserRole.TRAINING_COORDINATOR.value,
                         COORDINATOR_USER_ID, COORDINATOR_ALT_USER_ID),
}


def screening_findings_headers(screening_type: str):
    """Headers of the role that owns findings for this screening type."""
    role, user_id, _alt = SCREENING_AUTHORITY[screening_type]
    return build_user_headers(user_id, role)


def screening_adjudicate_headers(screening_type: str):
    """Headers of a second, distinct user of the owning role."""
    role, _user_id, alt = SCREENING_AUTHORITY[screening_type]
    return build_user_headers(alt, role)
