"""Operator identities and pre-built header sets.

PRD 2.1 splits identity resolution by role:

* For ``Registrar``, ``AcademicAdvisor``, ``CertificationOfficer``,
  ``LearningSpecialist``, ``AppealsCommittee``, ``ComplianceOfficer`` and
  ``AthleticsOperations`` the ``X-User-ID`` is an opaque operator identifier
  that is never compared to any entity id.
* For ``Instructor`` the ``X-User-ID`` is compared against the course's
  ``instructor_user_id``, so instructor identities are shared with the course
  factories.
* For ``Tutor`` the ``X-User-ID`` is the acting ``Tutor`` row id.
* For ``StudentAthlete`` the ``X-User-ID`` is the acting ``StudentAthlete``
  row id.

Segregation of duties (PRD 2.1) is an identity comparison, so this module
deliberately exposes several *distinct* operators per privileged role.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ACADEMIC_ADVISOR,
    ROLE_APPEALS_COMMITTEE,
    ROLE_ATHLETICS_OPERATIONS,
    ROLE_CERTIFICATION_OFFICER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_INSTRUCTOR,
    ROLE_LEARNING_SPECIALIST,
    ROLE_REGISTRAR,
    ROLE_STUDENT_ATHLETE,
    ROLE_TUTOR,
)

# ---------------------------------------------------------------------------
# Opaque operator identifiers.  Distinct owners always get distinct ids.
# ---------------------------------------------------------------------------
REGISTRAR_1 = "reg_1"
REGISTRAR_2 = "reg_2"

ADVISOR_1 = "adv_1"
ADVISOR_2 = "adv_2"

# Certification officers: the requester must differ from the decider.
CERT_OFFICER_REQUESTER = "co_requester"
CERT_OFFICER_DECIDER = "co_decider"
CERT_OFFICER_SUBMITTER = "co_submitter"

SPECIALIST_1 = "ls_1"
SPECIALIST_2 = "ls_2"

# Appeals committee members: the decider must differ from the submitter.
COMMITTEE_1 = "ac_1"
COMMITTEE_2 = "ac_2"

COMPLIANCE_1 = "cmp_1"
COMPLIANCE_2 = "cmp_2"

OPERATIONS_1 = "ops_1"
OPERATIONS_2 = "ops_2"

# Instructor-of-record identities.  These double as ``instructor_user_id``
# values on the courses created by the factories.
INSTRUCTOR_SOC_1 = "instr_soc_1"
INSTRUCTOR_MATH_1 = "instr_math_1"
INSTRUCTOR_MATH_2 = "instr_math_2"
INSTRUCTOR_KINE_1 = "instr_kine_1"
INSTRUCTOR_HIST_1 = "instr_hist_1"
INSTRUCTOR_ART_1 = "instr_art_1"
INSTRUCTOR_MUS_1 = "instr_mus_1"
INSTRUCTOR_PHIL_1 = "instr_phil_1"
INSTRUCTOR_ENGL_1 = "instr_engl_1"
INSTRUCTOR_BIO_1 = "instr_bio_1"

# ---------------------------------------------------------------------------
# Pre-built header sets for the opaque roles.
# ---------------------------------------------------------------------------
REGISTRAR = build_user_headers(REGISTRAR_1, ROLE_REGISTRAR)
REGISTRAR_ALT = build_user_headers(REGISTRAR_2, ROLE_REGISTRAR)

ADVISOR = build_user_headers(ADVISOR_1, ROLE_ACADEMIC_ADVISOR)
ADVISOR_ALT = build_user_headers(ADVISOR_2, ROLE_ACADEMIC_ADVISOR)

CERT_OFFICER = build_user_headers(CERT_OFFICER_REQUESTER, ROLE_CERTIFICATION_OFFICER)
CERT_OFFICER_ALT = build_user_headers(CERT_OFFICER_DECIDER, ROLE_CERTIFICATION_OFFICER)
CERT_OFFICER_THIRD = build_user_headers(
    CERT_OFFICER_SUBMITTER, ROLE_CERTIFICATION_OFFICER
)

SPECIALIST = build_user_headers(SPECIALIST_1, ROLE_LEARNING_SPECIALIST)
SPECIALIST_ALT = build_user_headers(SPECIALIST_2, ROLE_LEARNING_SPECIALIST)

COMMITTEE = build_user_headers(COMMITTEE_1, ROLE_APPEALS_COMMITTEE)
COMMITTEE_ALT = build_user_headers(COMMITTEE_2, ROLE_APPEALS_COMMITTEE)

COMPLIANCE = build_user_headers(COMPLIANCE_1, ROLE_COMPLIANCE_OFFICER)
COMPLIANCE_ALT = build_user_headers(COMPLIANCE_2, ROLE_COMPLIANCE_OFFICER)

OPERATIONS = build_user_headers(OPERATIONS_1, ROLE_ATHLETICS_OPERATIONS)
OPERATIONS_ALT = build_user_headers(OPERATIONS_2, ROLE_ATHLETICS_OPERATIONS)


# ---------------------------------------------------------------------------
# Identity-bound header builders.
# ---------------------------------------------------------------------------
def instructor_headers(instructor_user_id: str) -> dict:
    """Headers for the instructor of record whose opaque id is given."""
    return build_user_headers(instructor_user_id, ROLE_INSTRUCTOR)


def tutor_headers(tutor_id: str) -> dict:
    """Headers for a ``Tutor``; ``X-User-ID`` is the tutor's own row id."""
    return build_user_headers(tutor_id, ROLE_TUTOR)


def student_headers(student_athlete_id: str) -> dict:
    """Headers for a ``StudentAthlete``; ``X-User-ID`` is its own row id."""
    return build_user_headers(student_athlete_id, ROLE_STUDENT_ATHLETE)


def headers_for(role: str, user_id: str) -> dict:
    """Headers for an arbitrary role/id pair (used by role-matrix tests)."""
    return build_user_headers(user_id, role)


# ---------------------------------------------------------------------------
# Malformed header sets.  Blank values are the empty string, never whitespace:
# a whitespace-only header value is rejected by the HTTP client itself and
# would never reach the server.
# ---------------------------------------------------------------------------
NO_HEADERS: dict = {"Content-Type": "application/json"}

MISSING_USER_ID = {
    "X-User-Role": ROLE_REGISTRAR,
    "Content-Type": "application/json",
}

MISSING_ROLE = {
    "X-User-ID": REGISTRAR_1,
    "Content-Type": "application/json",
}

EMPTY_USER_ID = {
    "X-User-ID": "",
    "X-User-Role": ROLE_REGISTRAR,
    "Content-Type": "application/json",
}

EMPTY_ROLE = {
    "X-User-ID": REGISTRAR_1,
    "X-User-Role": "",
    "Content-Type": "application/json",
}

UNKNOWN_ROLE = {
    "X-User-ID": "who_1",
    "X-User-Role": "Provost",
    "Content-Type": "application/json",
}
