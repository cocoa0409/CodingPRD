"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the opaque roles (Anonymous, PlatformAdmin), and
# for tests that do not exercise ownership. For the entity-backed roles the
# shared constant is a fallback only; ownership-gated calls must use the
# make_*_headers builders below with the actual entity id.
TEST_USERS = {
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "career_center_admin_headers": build_user_headers(
        "test-career-center-admin-1", "CareerCenterAdmin"
    ),
    "employer_recruiter_headers": build_user_headers(
        "test-employer-recruiter-1", "EmployerRecruiter"
    ),
    "student_headers": build_user_headers("test-student-1", "Student"),
}


def make_career_center_admin_headers(university_id: str) -> dict:
    """For CareerCenterAdmin (entity-backed by University): X-User-ID must equal
    the administered university's id on every ownership-gated call."""
    return build_user_headers(university_id, "CareerCenterAdmin")


def make_employer_recruiter_headers(employer_id: str) -> dict:
    """For EmployerRecruiter (entity-backed by Employer): X-User-ID must equal
    the operated employer's id on every ownership-gated call."""
    return build_user_headers(employer_id, "EmployerRecruiter")


def make_student_headers(student_id: str) -> dict:
    """For Student (entity-backed by Student): X-User-ID must equal the acting
    student's id on every ownership-gated call."""
    return build_user_headers(student_id, "Student")
