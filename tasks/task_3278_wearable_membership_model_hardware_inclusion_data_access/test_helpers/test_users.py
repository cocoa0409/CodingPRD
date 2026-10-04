"""Pre-built role headers for every role in the PRD.

Anonymous, Coach, Support, and PlatformAdmin are opaque roles: the shared
constants are the canonical form. Member is entity-backed: ownership checks
compare the resource's member_id to X-User-ID, so ownership-gated calls MUST
use make_member_headers(member_id) with the real member id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "anonymous_headers": build_user_headers("anon-caller-1", "Anonymous"),
    "coach_headers": build_user_headers("coach-shared-1", "Coach"),
    "support_headers": build_user_headers("support-shared-1", "Support"),
    "platform_admin_headers": build_user_headers("admin-shared-1", "PlatformAdmin"),
    # Member is entity-backed: this fallback is only safe for calls whose
    # success does not depend on the caller owning the subject resource.
    "member_headers": build_user_headers("member-shared-1", "Member"),
}


def make_member_headers(member_id: str) -> dict:
    """For Member (entity-backed:Member). Pass the actual Member.id whenever
    the call is ownership-gated (terms, devices, merch orders, consents, ...)."""
    return build_user_headers(member_id, "Member")


def make_coach_headers(coach_user_id: str) -> dict:
    """For Coach. Team ownership compares the team's stored coach_user_id to
    X-User-ID; pass the same opaque id used when the team was created."""
    return build_user_headers(coach_user_id, "Coach")


def make_anonymous_headers(caller_id: str = "anon-caller-1") -> dict:
    return build_user_headers(caller_id, "Anonymous")


def make_support_headers(user_id: str = "support-shared-1") -> dict:
    return build_user_headers(user_id, "Support")


def make_platform_admin_headers(user_id: str = "admin-shared-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
