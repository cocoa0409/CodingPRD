"""Pre-built role headers for every role in the PRD.

``Anonymous``, ``StationOps``, ``PlatformAdmin`` and ``AppealsReviewer`` are
opaque identities whose ``X-User-ID`` is a free operator identifier; their
shared constants are the canonical form. ``Driver`` is entity-backed — its
``X-User-ID`` must be the ``id`` of the acting Driver row itself, so
ownership-gated calls must go through ``make_driver_headers(driver_id)``.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "anonymous_headers": build_user_headers("", "Anonymous"),
    "station_ops_headers": build_user_headers("test-station-ops-1", "StationOps"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "appeals_reviewer_headers": build_user_headers("test-reviewer-1", "AppealsReviewer"),
    # entity_backed: shared constant is a fallback for non-ownership tests only.
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
}


def make_driver_headers(user_id: str) -> dict:
    """For Driver (entity_backed:Driver).

    Pass the actual Driver row's id as user_id whenever the call is
    ownership-gated: ownership checks compare the resource's driver
    foreign-key field against ``X-User-ID``.
    """
    return build_user_headers(user_id, "Driver")
