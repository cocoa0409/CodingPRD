"""Pre-built role headers for every role the API recognizes (PRD §2.1).

``ProgramStaff`` and ``Anonymous`` are opaque identities: their ``X-User-ID``
is not tied to any persisted row, so the shared constants below are their
canonical form.  ``Partner`` and ``Student`` are entity-backed: their
``X-User-ID`` must be the ``id`` of an existing row of the backing entity, so
every ownership-gated call must use the matching ``make_*_headers`` builder
with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-applicant-1", "Anonymous"),
    "program_staff_headers": build_user_headers("staff-operator-1", "ProgramStaff"),
    # Fallbacks for calls that are not ownership-gated; ownership-gated calls
    # must use make_partner_headers(<partner id>) instead.
    "partner_headers": build_user_headers("test-partner-1", "Partner"),
    "student_headers": build_user_headers("test-student-1", "Student"),
}


def make_partner_headers(user_id: str) -> dict:
    """Headers for a Partner whose ``X-User-ID`` is the acting Partner's id."""
    return build_user_headers(user_id, "Partner")


def make_student_headers(user_id: str) -> dict:
    """Headers for a Student whose ``X-User-ID`` is the acting Student's id."""
    return build_user_headers(user_id, "Student")
