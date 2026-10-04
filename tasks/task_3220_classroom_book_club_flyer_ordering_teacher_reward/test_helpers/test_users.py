"""Caller identities and pre-built role headers.

Every request carries ``X-User-ID`` and ``X-User-Role`` headers. The Teacher
role is entity-backed: when ``X-User-Role`` is ``Teacher``, ``X-User-ID`` must
be the ``id`` of the acting Teacher entity, so ownership-guarded calls must
build headers with ``make_teacher_headers(teacher["id"])`` after creating the
teacher. The other four roles are opaque operator identifiers never matched
against a stored row, so a stable shared header set is correct for them.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Ready-made header dicts for the opaque roles. The Teacher entry is a
# fallback for calls whose success does not depend on the caller owning the
# subject resource; ownership-gated calls must use make_teacher_headers().
TEST_USERS: Dict[str, Dict[str, str]] = {
    "club_admin_headers": build_user_headers("test-club-admin-1", "ClubAdmin"),
    "school_admin_headers": build_user_headers("test-school-admin-1", "SchoolAdmin"),
    "teacher_headers": build_user_headers("test-teacher-1", "Teacher"),
    "parent_headers": build_user_headers("test-parent-1", "Parent"),
    "donor_headers": build_user_headers("test-donor-1", "Donor"),
}


def make_teacher_headers(teacher_id: str) -> Dict[str, str]:
    """Headers for the entity-backed Teacher role.

    Pass the actual Teacher row's ``id`` whenever the call is
    ownership-gated (class order submit/cancel, redemption confirm/cancel,
    donation request create, ledger reads).
    """
    return build_user_headers(teacher_id, "Teacher")
