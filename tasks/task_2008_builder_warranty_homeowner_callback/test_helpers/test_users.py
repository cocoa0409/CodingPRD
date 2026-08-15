"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for entity-backed roles only in
# tests whose success does NOT depend on owning the subject resource (e.g.
# 400-on-bad-payload, 404-on-missing-resource).
TEST_USERS = {
    # entity_backed:Homeowner — fallback for non-ownership tests only.
    "homeowner_headers": build_user_headers("test-homeowner-1", "Homeowner"),
    # opaque roles — canonical form.
    "rep_headers": build_user_headers("test-rep-1", "WarrantyRep"),
    "manager_headers": build_user_headers("test-manager-1", "WarrantyManager"),
    "finance_headers": build_user_headers("test-finance-1", "FinanceAdmin"),
    "admin_headers": build_user_headers("test-admin-1", "WarrantyAdministrator"),
    # entity_backed:TradePartner — fallback for non-ownership tests only.
    "trade_partner_headers": build_user_headers("test-partner-1", "TradePartner"),
}


def make_homeowner_headers(homeowner_id: str) -> dict:
    """Homeowner is entity-backed (PRD §2.1): pass the actual Homeowner.id as
    user_id whenever the call is ownership-gated (intake, dispute, verify)."""
    return build_user_headers(homeowner_id, "Homeowner")


def make_trade_partner_headers(partner_id: str) -> dict:
    """TradePartner is entity-backed (PRD §2.1): pass the actual TradePartner.id
    as user_id whenever the call is ownership-gated (complete, contest)."""
    return build_user_headers(partner_id, "TradePartner")
