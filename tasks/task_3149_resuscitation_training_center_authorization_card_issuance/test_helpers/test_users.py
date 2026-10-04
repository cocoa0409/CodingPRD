"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for entity-backed roles in
# tests that do not exercise ownership gating.
TEST_USERS = {
    "national_admin_headers": build_user_headers("test-admin-1", "NationalAdmin"),
    "tc_admin_headers": build_user_headers("test-tc-admin-1", "TCAdmin"),
    "coordinator_headers": build_user_headers("test-coordinator-1", "TCCoordinator"),
    # entity_backed:Instructor — fallback for non-ownership contexts only.
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    # entity_backed:Instructor — fallback for non-ownership contexts only.
    "faculty_headers": build_user_headers("test-faculty-1", "TrainingFaculty"),
    "qa_auditor_headers": build_user_headers("test-auditor-1", "QAAuditor"),
    "employer_headers": build_user_headers("test-employer-1", "Employer"),
}


def make_instructor_headers(instructor_id: str) -> dict:
    """For Instructor (entity_backed:Instructor). Pass the actual Instructor.id
    whenever the call is ownership-gated (session lead, skills evaluation)."""
    return build_user_headers(instructor_id, "Instructor")


def make_faculty_headers(instructor_id: str) -> dict:
    """For TrainingFaculty (entity_backed:Instructor). Pass the actual faculty
    Instructor.id whenever the call resolves the faculty from X-User-ID."""
    return build_user_headers(instructor_id, "TrainingFaculty")
