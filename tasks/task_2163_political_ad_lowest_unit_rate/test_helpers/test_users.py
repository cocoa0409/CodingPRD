"""Pre-built role headers for every role in the PRD.

Four of the five roles carry an opaque operator identifier in ``X-User-ID`` that
is never compared to any entity's ``id``.  ``AdvertiserAgent`` is different: its
``X-User-ID`` is the ``id`` of the acting advertiser, and every ownership check
compares the resource's advertiser foreign key to it -- so an AdvertiserAgent
call must always be built with :func:`make_advertiser_agent_headers`.

Two distinct compliance-officer principals exist because the segregation-of-duties
rule on complaint responses is enforced on the person, not on the role.
"""

from prd_bench_local_runner.testing import build_user_headers

ADMIN_USER_ID = "admin-01"
OFFICER_ALPHA_USER_ID = "officer-alpha"
OFFICER_BETA_USER_ID = "officer-beta"
TRAFFIC_USER_ID = "traffic-01"
PUBLIC_USER_ID = "public-77"
PUBLIC_SECOND_USER_ID = "public-78"

TEST_USERS = {
    "platform_admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    # officer-alpha classifies advertisers and posts the public file.
    "officer_alpha_headers": build_user_headers(
        OFFICER_ALPHA_USER_ID, "StationComplianceOfficer"
    ),
    # officer-beta decides order acceptance, so it is the principal barred from
    # answering a complaint that names an order it accepted.
    "officer_beta_headers": build_user_headers(
        OFFICER_BETA_USER_ID, "StationComplianceOfficer"
    ),
    "traffic_scheduler_headers": build_user_headers(TRAFFIC_USER_ID, "TrafficScheduler"),
    "public_complainant_headers": build_user_headers(PUBLIC_USER_ID, "PublicComplainant"),
    "second_complainant_headers": build_user_headers(
        PUBLIC_SECOND_USER_ID, "PublicComplainant"
    ),
    # Placeholder only: any AdvertiserAgent call that touches an ownership check
    # must use make_advertiser_agent_headers(advertiser["id"]) instead.
    "advertiser_agent_headers": build_user_headers("agent-unbound", "AdvertiserAgent"),
}


def make_advertiser_agent_headers(advertiser_id: str) -> dict:
    """Headers for the AdvertiserAgent acting for the advertiser whose id is given.

    Pass the real advertiser id: ownership checks compare the resource's
    ``advertiser_id`` or ``requesting_advertiser_id`` to this value.
    """
    return build_user_headers(advertiser_id, "AdvertiserAgent")


def make_officer_headers(user_id: str) -> dict:
    """Headers for a named StationComplianceOfficer principal."""
    return build_user_headers(user_id, "StationComplianceOfficer")


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_headers_without_auth() -> dict:
    """Headers carrying neither X-User-ID nor X-User-Role."""
    return {"Content-Type": "application/json"}
