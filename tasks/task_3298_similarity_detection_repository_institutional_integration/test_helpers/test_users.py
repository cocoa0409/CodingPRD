"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, cross-tenant reads).
TEST_USERS = {
    # Opaque roles: the server does not compare X-User-ID to any entity id.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "institutional_admin_headers": build_user_headers("test-institutional-admin-1", "InstitutionalAdmin"),
    # Entity-backed roles: shared constants ONLY for non-ownership tests.
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    "student_headers": build_user_headers("test-student-1", "Student"),
}


def make_instructor_headers(user_id: str) -> dict:
    """For Instructor (entity-backed). Pass the actual Instructor.id as user_id
    whenever the call is ownership-gated (assignment writes, finalize, grading)."""
    return build_user_headers(user_id, "Instructor")


def make_student_headers(user_id: str) -> dict:
    """For Student (entity-backed). Pass the actual Student.id as user_id
    whenever the call is ownership-gated (intake, consents, own reads)."""
    return build_user_headers(user_id, "Student")
