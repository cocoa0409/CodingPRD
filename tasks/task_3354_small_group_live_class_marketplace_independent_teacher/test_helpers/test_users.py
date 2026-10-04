"""Pre-built role headers for every role in the PRD (§2.1).

`Teacher` is the only entity-backed role: its X-User-ID must be the acting Teacher
entity's own `id`, so ownership-gated calls must use `make_teacher_headers(teacher_id)`.
The shared constant is only a fallback for calls that never touch ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "teacher_reviewer_headers": build_user_headers("rev_1", "TeacherReviewer"),
    "teacher_applicant_headers": build_user_headers("u_ada", "TeacherApplicant"),
    # entity_backed role: fallback for non-ownership calls only.
    "teacher_headers": build_user_headers("teacher-1", "Teacher"),
    "parent_headers": build_user_headers("p_1", "Parent"),
}


def make_platform_admin_headers(admin_user_id: str = "admin-1") -> dict:
    """PlatformAdmin acts under a fully opaque operator identifier."""
    return build_user_headers(admin_user_id, "PlatformAdmin")


def make_teacher_reviewer_headers(reviewer_user_id: str = "rev_1") -> dict:
    """TeacherReviewer binds as `reviewed_by_user_id` when it decides a file."""
    return build_user_headers(reviewer_user_id, "TeacherReviewer")


def make_teacher_applicant_headers(applicant_user_id: str = "u_ada") -> dict:
    """TeacherApplicant is recorded as the application's `applicant_user_id`."""
    return build_user_headers(applicant_user_id, "TeacherApplicant")


def make_teacher_headers(teacher_id: str) -> dict:
    """For Teacher (entity_backed:Teacher). Pass the actual Teacher.id whenever the
    call is ownership-gated (publish, section cancel, payout request)."""
    return build_user_headers(teacher_id, "Teacher")


def make_parent_headers(parent_user_id: str = "p_1") -> dict:
    """Parent acts under an opaque operator identifier compared to `parent_user_id`."""
    return build_user_headers(parent_user_id, "Parent")
