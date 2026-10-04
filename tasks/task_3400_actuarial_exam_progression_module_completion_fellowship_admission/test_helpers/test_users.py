"""Pre-built role headers for every role in the PRD (§2.1).

- Candidate is entity_backed:Candidate — ownership checks compare a resource's
  candidate_id (or the path candidate id) to X-User-ID, so ownership-gated
  calls MUST use make_candidate_headers(candidate["id"]) after creation.
- Registrar, ExamCommittee, AcademicReviewer, Grader and DisciplineBoard are
  opaque operator roles: the shared constant is the canonical form. Grader
  identity is recorded into ProjectAssessment.grader_ids and is subject to
  segregation of duties, so grading sequences use make_grader_headers() with
  distinct ids.
- Anonymous is unauthenticated self-registration: X-User-ID is not required
  and never compared to any persisted entity; the shared constant still sends
  an opaque id, which is harmless.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, unauthorized-role).
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-self-reg-1", "Anonymous"),
    # Candidate: fallback for non-ownership tests only; ownership-gated calls
    # must thread the real Candidate.id via make_candidate_headers().
    "candidate_headers": build_user_headers("candidate-fallback-1", "Candidate"),
    "registrar_headers": build_user_headers("registrar-1", "Registrar"),
    "exam_committee_headers": build_user_headers("committee-1", "ExamCommittee"),
    "academic_reviewer_headers": build_user_headers("reviewer-1", "AcademicReviewer"),
    "grader_headers": build_user_headers("grader-001", "Grader"),
    "discipline_board_headers": build_user_headers("board-1", "DisciplineBoard"),
}

ANONYMOUS = TEST_USERS["anonymous_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
EXAM_COMMITTEE = TEST_USERS["exam_committee_headers"]
ACADEMIC_REVIEWER = TEST_USERS["academic_reviewer_headers"]
DISCIPLINE_BOARD = TEST_USERS["discipline_board_headers"]

# Header variants for the authentication-header precedence probe (PRD §2.8
# priority 1): a request missing X-User-Role, and a request with an
# undeclared role, are both rejected with ERR_MISSING_HEADERS (401).
NO_ROLE_HEADERS = {"X-User-ID": "user-no-role-1", "Content-Type": "application/json"}
UNDECLARED_ROLE_HEADERS = build_user_headers("user-bad-role-1", "SuperUser")


def make_candidate_headers(user_id: str) -> dict:
    """For Candidate (entity_backed:Candidate). Pass the actual Candidate.id
    whenever the call is ownership-gated (registrations, VEE, enrollments,
    attempts, projects, attendances, transfers, attestations, applications)."""
    return build_user_headers(user_id, "Candidate")


def make_grader_headers(user_id: str) -> dict:
    """For Grader (opaque, but recorded into grader_ids). Use a distinct id per
    grader in a consensus/split sequence to respect segregation of duties."""
    return build_user_headers(user_id, "Grader")


def make_registrar_headers(user_id: str = "registrar-1") -> dict:
    return build_user_headers(user_id, "Registrar")


def make_exam_committee_headers(user_id: str = "committee-1") -> dict:
    return build_user_headers(user_id, "ExamCommittee")


def make_academic_reviewer_headers(user_id: str = "reviewer-1") -> dict:
    return build_user_headers(user_id, "AcademicReviewer")


def make_discipline_board_headers(user_id: str = "board-1") -> dict:
    return build_user_headers(user_id, "DisciplineBoard")


def make_anonymous_headers(user_id: str = "anon-self-reg-1") -> dict:
    return build_user_headers(user_id, "Anonymous")
