"""Pre-built role headers for every role in the PRD.

Two of the eight roles are backed by persisted StaffShift rows. For those roles
the server compares the resource's foreign-key field (a GuestCheck's
`presented_shift_id`, a StaffShift's `crossover_authorized_by_shift_id`) against
`X-User-ID`, so a caller must pass a *real* StaffShift id. The shared constants
below carry a placeholder for those two roles and are usable only where the call
is not ownership-gated; ownership-gated calls must use the per-instance builders.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the six opaque roles, and for entity-backed roles
# only on calls that do not compare a foreign key against X-User-ID.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "assortment_planner_headers": build_user_headers("test-assortment-planner-1", "AssortmentPlanner"),
    "boutique_manager_headers": build_user_headers("test-boutique-manager-1", "BoutiqueManager"),
    "retail_lead_headers": build_user_headers("test-retail-lead-1", "RetailLead"),
    "retail_cashier_headers": build_user_headers("test-retail-cashier-1", "RetailCashier"),
    # entity_backed:StaffShift — placeholder only; prefer the builders below.
    "cashier_headers": build_user_headers("test-cashier-1", "Cashier"),
    # entity_backed:StaffShift — placeholder only; prefer the builders below.
    "server_headers": build_user_headers("test-server-1", "Server"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
}

# Headers that are deliberately absent, for the unauthenticated-rejection rule.
NO_ROLE_HEADERS = {"X-User-ID": "test-no-role-1", "Content-Type": "application/json"}
NO_USER_HEADERS = {"X-User-Role": "BoutiqueManager", "Content-Type": "application/json"}
EMPTY_HEADERS = {"Content-Type": "application/json"}


def make_cashier_headers(user_id: str) -> dict:
    """For Cashier (entity_backed:StaffShift). Pass the acting StaffShift.id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Cashier")


def make_server_headers(user_id: str) -> dict:
    """For Server (entity_backed:StaffShift). Pass the acting StaffShift.id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Server")