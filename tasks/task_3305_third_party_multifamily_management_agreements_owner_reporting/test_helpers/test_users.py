"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership. OwnerRep is entity-backed: use make_owner_rep_headers(owner_id)
# for any ownership-gated call.
TEST_USERS = {
    "pm_headers": build_user_headers("test-pm-1", "PortfolioManager"),
    "acct_headers": build_user_headers("test-acct-1", "PropertyAccountant"),
    "analyst_headers": build_user_headers("test-analyst-1", "RevenueAnalyst"),
    "risk_headers": build_user_headers("test-risk-1", "RiskOfficer"),
    # Fallback only for non-ownership assertions (e.g. RBAC denial probes).
    "owner_headers": build_user_headers("test-owner-fallback", "OwnerRep"),
}


def make_owner_rep_headers(user_id: str) -> dict:
    """OwnerRep is entity-backed by Owner (PRD §2.1): pass the real Owner.id
    whenever the call is ownership-gated (terminate, approve/reject, override,
    disposition)."""
    return build_user_headers(user_id, "OwnerRep")


def make_pm_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PortfolioManager")


def make_acct_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PropertyAccountant")
