"""Pre-built role headers for every role in the PRD.

The four non-partner roles are opaque: X-User-ID is not tied to any entity.
TRADE_PARTNER is entity-backed: X-User-ID must equal the acting TradePartner's
id, so ownership-gated calls must go through make_trade_partner_headers().
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "division_president_headers": build_user_headers("test-dp-1", "DIVISION_PRESIDENT"),
    "land_manager_headers": build_user_headers("test-lm-1", "LAND_MANAGER"),
    "community_manager_headers": build_user_headers("test-cm-1", "COMMUNITY_MANAGER"),
    "sales_agent_headers": build_user_headers("test-sa-1", "SALES_AGENT"),
    # Fallback for non-ownership uses only (e.g., reads).
    "trade_partner_headers": build_user_headers("test-tp-1", "TRADE_PARTNER"),
}


def make_trade_partner_headers(trade_partner_id: str) -> dict:
    """TRADE_PARTNER is entity-backed: X-User-ID must equal the TradePartner id
    whenever the call is ownership-gated (create/reduce capacity commitments)."""
    return build_user_headers(trade_partner_id, "TRADE_PARTNER")
