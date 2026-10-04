"""Pre-built role headers for every declared role (PRD section 2.1).

`MembershipOwner` is the only entity-backed role: `X-User-ID` must be the `id`
of the acting Membership. The shared constant below is a fallback used only by
tests whose outcome does not depend on ownership; every ownership-gated call
must use `make_membership_owner_headers(<membership id>)` instead.

The remaining four roles are opaque, so their shared constants are canonical.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # MembershipOwner is entity_backed:Membership — the shared constant is a
    # fallback for calls that are not ownership-gated.
    "membership_owner_headers": build_user_headers("test-owner-1", "MembershipOwner"),
    "service_technician_headers": build_user_headers("test-technician-1", "ServiceTechnician"),
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
}


def make_membership_owner_headers(membership_id: str) -> dict:
    """For MembershipOwner (entity_backed:Membership).

    Pass the acting Membership's own `id` as the user id whenever the call is
    ownership-gated, so the resource's membership foreign key equals X-User-ID.
    """
    return build_user_headers(membership_id, "MembershipOwner")


def opaque_headers(role: str) -> dict:
    """Headers for one of the four opaque roles, keyed by role name."""
    return build_user_headers(f"test-{role.lower()}-1", role)