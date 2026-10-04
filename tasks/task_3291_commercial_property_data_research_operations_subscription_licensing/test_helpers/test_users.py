"""Access role headers for every role the API recognizes.

Entity-backed roles carry the ``User.id`` of the acting row in ``X-User-ID``,
so their per-instance builders below are required whenever a call is
ownership- or scope-gated. ``PlatformAdmin`` is opaque: its identifier is not
tied to a persisted entity and is never compared to one.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identity — safe as a shared constant.
    "platform_admin_headers": build_user_headers("test-platform-admin", "PlatformAdmin"),
    # Entity-backed fallbacks — use these only for calls that do not depend on
    # the caller owning or being scoped to the subject resource.
    "research_analyst_headers": build_user_headers("test-analyst-tx", "ResearchAnalyst"),
    "seat_user_headers": build_user_headers("test-seat-user", "SeatUser"),
    "licensing_admin_headers": build_user_headers("test-licensing-admin", "LicensingAdmin"),
    "enforcement_officer_headers": build_user_headers("test-enforcement-officer", "EnforcementOfficer"),
    "broker_publisher_headers": build_user_headers("test-broker-publisher", "BrokerPublisher"),
}


def make_research_analyst_headers(user_id: str) -> dict:
    """ResearchAnalyst is entity-backed: pass the acting User.id.

    Scoped research operations resolve the acting analyst's ``assigned_market``
    from that User row, so an arbitrary string never resolves.
    """
    return build_user_headers(user_id, "ResearchAnalyst")


def make_seat_user_headers(user_id: str) -> dict:
    """SeatUser is entity-backed: pass the acting User.id."""
    return build_user_headers(user_id, "SeatUser")


def make_licensing_admin_headers(user_id: str) -> dict:
    """LicensingAdmin is entity-backed: pass the acting User.id."""
    return build_user_headers(user_id, "LicensingAdmin")


def make_enforcement_officer_headers(user_id: str) -> dict:
    """EnforcementOfficer is entity-backed: pass the acting User.id."""
    return build_user_headers(user_id, "EnforcementOfficer")


def make_broker_publisher_headers(user_id: str) -> dict:
    """BrokerPublisher is entity-backed: pass the acting User.id.

    Listing publication also checks that the listing's organization is the
    acting user's organization.
    """
    return build_user_headers(user_id, "BrokerPublisher")