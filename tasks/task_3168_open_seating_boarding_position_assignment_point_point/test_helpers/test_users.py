"""Pre-built role headers for every role in the API.

``Passenger`` is entity-backed: its ``X-User-ID`` is the id of an actual
``Passenger`` entity, and ownership checks compare that identifier to the
resource's ``passenger_id``. The shared constant below is therefore only safe
for requests that do not exercise ownership; every ownership-gated call must
use ``make_passenger_headers`` with the real entity's ``id``.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — the shared constant is the canonical form.
    "gate_agent_headers": build_user_headers("test-gate-1", "GateAgent"),
    "ops_headers": build_user_headers("test-ops-1", "OpsController"),
    # entity_backed role — fallback for non-ownership requests only.
    "passenger_headers": build_user_headers("test-passenger-1", "Passenger"),
}

# No user context at all — used to exercise the identity check.
NO_USER_HEADERS: dict = {"Content-Type": "application/json"}


def make_passenger_headers(passenger_id: str) -> dict:
    """Headers for a Passenger acting as itself. Pass the real Passenger.id
    whenever the call is ownership-gated (check-in, cancel, change, upgrade
    purchase/refund, credit redemption)."""
    return build_user_headers(passenger_id, "Passenger")


def make_role_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary identity/role pair."""
    return build_user_headers(user_id, role)
