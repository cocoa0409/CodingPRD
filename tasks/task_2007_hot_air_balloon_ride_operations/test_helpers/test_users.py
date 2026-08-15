"""Pre-built role headers for every role in the PRD (§2.1).

OperationsManager, ChaseCrewLead, and Anonymous carry opaque identifiers never
compared to any entity id, so the shared constants are canonical for them.
Pilot and Customer are entity-backed: when the call is ownership-gated,
X-User-ID must be the acting entity's id — use make_pilot_headers(pilot["id"])
/ make_customer_headers(customer["id"]) for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, ops-desk calls).
TEST_USERS = {
    "ops_headers": build_user_headers("test-ops-1", "OperationsManager"),
    "chase_headers": build_user_headers("test-chase-1", "ChaseCrewLead"),
    "anon_headers": build_user_headers("test-anon-1", "Anonymous"),
    # entity_backed roles: shared constants are fallbacks for non-ownership
    # tests only (e.g. reading a resource, or a 404/400 assertion).
    "pilot_headers": build_user_headers("test-pilot-1", "Pilot"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_ops_headers(user_id: str = "test-ops-1") -> dict:
    return build_user_headers(user_id, "OperationsManager")


def make_chase_headers(user_id: str = "test-chase-1") -> dict:
    return build_user_headers(user_id, "ChaseCrewLead")


def make_anon_headers(user_id: str = "test-anon-1") -> dict:
    return build_user_headers(user_id, "Anonymous")


def make_pilot_headers(user_id: str) -> dict:
    """For Pilot (entity-backed by Pilot). Pass the acting Pilot.id whenever
    the call is pilot-scoped (flight events, weather briefings)."""
    return build_user_headers(user_id, "Pilot")


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity-backed by Customer). Pass the acting Customer.id
    whenever the call is ownership-gated (booking, CONFIRM/CANCEL, manifest)."""
    return build_user_headers(user_id, "Customer")
