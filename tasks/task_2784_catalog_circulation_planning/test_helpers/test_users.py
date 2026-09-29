"""Pre-built operator headers for every role the PRD declares.

``X-User-ID`` is an opaque operator identifier that is never compared against
any entity's ``id``; the only place the server records it is the three
operator-stamp fields on a circulation plan. Tests that need two distinct
operators in the same role — the segregation-of-duties path — use the
``make_*_headers`` builders below to vary the identifier.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — every role is opaque, so these are the canonical form.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("u-admin-1", "PlatformAdmin"),
    "circulation_planner_headers": build_user_headers(
        "u-planner-1", "CirculationPlanner"
    ),
    "circulation_director_headers": build_user_headers(
        "u-director-9", "CirculationDirector"
    ),
    "list_broker_headers": build_user_headers("u-broker-1", "ListBroker"),
    "marketing_analyst_headers": build_user_headers("u-analyst-1", "MarketingAnalyst"),
}

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["circulation_planner_headers"]
DIRECTOR = TEST_USERS["circulation_director_headers"]
BROKER = TEST_USERS["list_broker_headers"]
ANALYST = TEST_USERS["marketing_analyst_headers"]


def make_platform_admin_headers(user_id: str) -> dict:
    """Headers for a specific PlatformAdmin operator identifier."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_circulation_planner_headers(user_id: str) -> dict:
    """Headers for a specific CirculationPlanner operator identifier.

    Used wherever a plan must be costed by one planner and submitted by
    another so the approval guard has two distinct identities to compare.
    """
    return build_user_headers(user_id, "CirculationPlanner")


def make_circulation_director_headers(user_id: str) -> dict:
    """Headers for a specific CirculationDirector operator identifier."""
    return build_user_headers(user_id, "CirculationDirector")


def make_list_broker_headers(user_id: str) -> dict:
    """Headers for a specific ListBroker operator identifier."""
    return build_user_headers(user_id, "ListBroker")


def make_marketing_analyst_headers(user_id: str) -> dict:
    """Headers for a specific MarketingAnalyst operator identifier."""
    return build_user_headers(user_id, "MarketingAnalyst")


# Named operator identities reused by the approval-path tests.
PLANNER_1 = make_circulation_planner_headers("u-planner-1")
PLANNER_2 = make_circulation_planner_headers("u-planner-2")
PLANNER_3 = make_circulation_planner_headers("u-planner-3")
PLANNER_4 = make_circulation_planner_headers("u-planner-4")
DIRECTOR_9 = make_circulation_director_headers("u-director-9")

ALL_ROLE_HEADERS = {
    "PlatformAdmin": ADMIN,
    "CirculationPlanner": PLANNER,
    "CirculationDirector": DIRECTOR,
    "ListBroker": BROKER,
    "MarketingAnalyst": ANALYST,
}
