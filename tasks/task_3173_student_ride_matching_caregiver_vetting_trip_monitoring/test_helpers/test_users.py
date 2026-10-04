"""Pre-built role headers.

Only the ``Driver`` role is entity-backed: for a Driver, ``X-User-ID`` is the
``id`` of the acting Driver entity, and every driver-scoped trip action requires
it to equal the trip's assigned driver. The other four roles carry opaque
operator identifiers and never need an entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    "district_admin_headers": build_user_headers("test-district-admin-1", "DistrictAdmin"),
    "support_center_headers": build_user_headers("test-support-agent-1", "SupportCenterAgent"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    # entity_backed role: the shared constant is a fallback for calls that do not
    # exercise ownership. Ownership-gated calls MUST use make_driver_headers().
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
}


def make_driver_headers(user_id: str) -> dict:
    """Headers for the Driver role, bound to the acting Driver entity's id.

    Every driver-scoped trip action (accept, arrive, depart, handoffs,
    exceptions) requires ``X-User-ID`` to equal the trip's assigned driver, so
    pass the real ``Driver.id`` whenever the call is ownership-gated.
    """
    return build_user_headers(user_id, "Driver")


__all__ = ["TEST_USERS", "make_driver_headers"]