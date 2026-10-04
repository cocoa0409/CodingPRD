"""Pre-built role headers for every role in the PRD (section 2.1).

Two identity shapes exist:

- Opaque roles (SocietyAdmin, AccreditationReviewer, Registrar, Consultant):
  the ``X-User-ID`` is an operator identifier the server never compares to
  an entity ``id`` — except the consultant id, which IS recorded on visits
  (``consultant_id``) and audits (``auditor_consultant_id``) and compared at
  report-filing / visit-linked-audit time. Shared constants are canonical.

- Entity-backed roles (SchoolAdmin -> School.id, ProgramDirector ->
  TeacherEducationProgram.id, AdultLearner -> AdultLearner.id): ownership
  checks compare ``X-User-ID`` to the entity's ``id``, so any call gated on
  ownership MUST use the per-instance builder with the real entity id.
  The shared constants for these roles exist only for tests whose outcome
  does not depend on ownership (400-shape, 404-existence, role-level 403).

Anonymous carries no identity headers at all (the two public directory
reads accept it); ``anonymous_headers`` is therefore an empty dict, and it
is also the header set used to probe ERR_UNAUTHENTICATED on locked
endpoints.

Two ids per opaque decision-making role are provided because segregation
of duties and multi-actor scenarios need distinct operator ids.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ---------------------------------------------------------------------------
# Opaque operator identifiers
# ---------------------------------------------------------------------------
SOCIETY_ADMIN_USER_ID = "soc-admin-1"
ACCREDITATION_REVIEWER_USER_ID = "rev-quinn"
ACCREDITATION_REVIEWER_2_USER_ID = "rev-mira"
REGISTRAR_USER_ID = "reg-otto"
CONSULTANT_USER_ID = "con-ada"
CONSULTANT_2_USER_ID = "con-zed"

# Fallback ids for the entity-backed roles — safe ONLY where no ownership
# check is exercised (they never equal a real entity id).
_TEST_SCHOOL_ADMIN_ID = "test-school-admin-1"
_TEST_PROGRAM_DIRECTOR_ID = "test-program-director-1"
_TEST_ADULT_LEARNER_ID = "test-adult-learner-1"

# ---------------------------------------------------------------------------
# Shared header sets
# ---------------------------------------------------------------------------
TEST_USERS = {
    # Opaque roles — canonical form.
    "society_admin_headers": build_user_headers(
        SOCIETY_ADMIN_USER_ID, UserRole.SOCIETY_ADMIN.value
    ),
    "accreditation_reviewer_headers": build_user_headers(
        ACCREDITATION_REVIEWER_USER_ID, UserRole.ACCREDITATION_REVIEWER.value
    ),
    "accreditation_reviewer_2_headers": build_user_headers(
        ACCREDITATION_REVIEWER_2_USER_ID, UserRole.ACCREDITATION_REVIEWER.value
    ),
    "registrar_headers": build_user_headers(REGISTRAR_USER_ID, UserRole.REGISTRAR.value),
    "consultant_headers": build_user_headers(CONSULTANT_USER_ID, UserRole.CONSULTANT.value),
    "consultant_2_headers": build_user_headers(
        CONSULTANT_2_USER_ID, UserRole.CONSULTANT.value
    ),
    # Entity-backed roles — fallback for non-ownership tests ONLY. Any call
    # gated on ownership must use the make_*_headers builders below.
    "school_admin_headers": build_user_headers(
        _TEST_SCHOOL_ADMIN_ID, UserRole.SCHOOL_ADMIN.value
    ),
    "program_director_headers": build_user_headers(
        _TEST_PROGRAM_DIRECTOR_ID, UserRole.PROGRAM_DIRECTOR.value
    ),
    "adult_learner_headers": build_user_headers(
        _TEST_ADULT_LEARNER_ID, UserRole.ADULT_LEARNER.value
    ),
    # Public caller — no identity headers (directory endpoints only).
    "anonymous_headers": {},
}

# Convenient module-level aliases for the opaque roles.
SOCIETY_ADMIN = TEST_USERS["society_admin_headers"]
ACCREDITATION_REVIEWER = TEST_USERS["accreditation_reviewer_headers"]
ACCREDITATION_REVIEWER_2 = TEST_USERS["accreditation_reviewer_2_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
CONSULTANT = TEST_USERS["consultant_headers"]
CONSULTANT_2 = TEST_USERS["consultant_2_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for entity-backed roles when the call is
# ownership-gated (PRD section 2.1: X-User-ID equals the entity's id).
# ---------------------------------------------------------------------------
def make_school_admin_headers(school_id: str) -> dict:
    """SchoolAdmin headers for the actor who owns the school ``school_id``."""
    return build_user_headers(school_id, UserRole.SCHOOL_ADMIN.value)


def make_program_director_headers(program_id: str) -> dict:
    """ProgramDirector headers for the actor who owns program ``program_id``."""
    return build_user_headers(program_id, UserRole.PROGRAM_DIRECTOR.value)


def make_adult_learner_headers(learner_id: str) -> dict:
    """AdultLearner headers for the learner row ``learner_id`` itself."""
    return build_user_headers(learner_id, UserRole.ADULT_LEARNER.value)


def make_consultant_headers(consultant_id: str) -> dict:
    """Consultant headers for a specific operator id — needed when a visit's
    recorded ``consultant_id`` must match the filer's ``X-User-ID``."""
    return build_user_headers(consultant_id, UserRole.CONSULTANT.value)


def make_reviewer_headers(reviewer_user_id: str) -> dict:
    """AccreditationReviewer headers for a specific operator id — needed to
    steer segregation-of-duties scenarios (reviewer != visit consultant)."""
    return build_user_headers(reviewer_user_id, UserRole.ACCREDITATION_REVIEWER.value)


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary user/role pairing, including deliberate mismatches."""
    return build_user_headers(user_id, role)
