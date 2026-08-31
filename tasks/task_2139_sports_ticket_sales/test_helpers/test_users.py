"""Pre-built role headers for every role in the PRD.

TicketOpsAdmin and RevenueManager carry opaque operator identifiers that the
server never compares to an entity id, so the shared constants below are the
canonical form for those two roles.

SalesRep identities are ServiceRep ids and AccountHolder identities are
TicketAccount ids, so every ownership-gated call must build headers from the
real entity id with the per-instance builders.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identities.
    "ops_admin_headers": build_user_headers("ops-admin-1", "TicketOpsAdmin"),
    "revenue_manager_headers": build_user_headers("rm-001", "RevenueManager"),
    "second_revenue_manager_headers": build_user_headers("rm-002", "RevenueManager"),
    # Entity-backed identities: fallbacks for tests that never touch ownership.
    "sales_rep_headers": build_user_headers("rep-not-real", "SalesRep"),
    "account_holder_headers": build_user_headers("acct-not-real", "AccountHolder"),
}

# Headers with no identity at all, for the unauthenticated path.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_ops_admin_headers(user_id="ops-admin-1"):
    """TicketOpsAdmin identity is opaque and never compared to an entity id."""
    return build_user_headers(user_id, "TicketOpsAdmin")


def make_revenue_manager_headers(user_id="rm-001"):
    """RevenueManager identity is opaque; it is recorded, never matched to an id."""
    return build_user_headers(user_id, "RevenueManager")


def make_sales_rep_headers(rep_id):
    """SalesRep identity is a ServiceRep id. Pass the account's assigned_rep_id."""
    return build_user_headers(rep_id, "SalesRep")


def make_account_holder_headers(account_id):
    """AccountHolder identity is a TicketAccount id. Pass the owning account id."""
    return build_user_headers(account_id, "AccountHolder")
