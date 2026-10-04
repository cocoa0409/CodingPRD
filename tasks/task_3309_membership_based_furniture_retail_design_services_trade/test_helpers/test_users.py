"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# entity-backed ownership. Member/TradeDesigner tests that exercise ownership
# MUST use the per-instance builders below with the real entity id.
TEST_USERS = {
    # entity_backed:Member — fallback for non-ownership flows only.
    "member_headers": build_user_headers("test-member-1", "Member"),
    # entity_backed:TradeAccount — fallback for non-ownership flows only.
    "trade_designer_headers": build_user_headers("test-trade-1", "TradeDesigner"),
    # Opaque roles — canonical form.
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    "gallery_associate_headers": build_user_headers("test-associate-1", "GalleryAssociate"),
    "trade_reviewer_headers": build_user_headers("test-reviewer-1", "TradeReviewer"),
    "production_planner_headers": build_user_headers("test-planner-1", "ProductionPlanner"),
    "hub_operator_headers": build_user_headers("test-hub-1", "HubOperator"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_member_headers(user_id: str) -> dict:
    """Member is entity-backed: pass the actual Member.id as user_id whenever
    the call is ownership-gated (member reads, renew, cancel, own orders)."""
    return build_user_headers(user_id, "Member")


def make_trade_designer_headers(user_id: str) -> dict:
    """TradeDesigner is entity-backed: pass the actual TradeAccount.id as user_id
    whenever the call is ownership-gated (trade order create / own orders)."""
    return build_user_headers(user_id, "TradeDesigner")
