"""Pre-built role headers for every role in the PRD.

SystemAdmin, PassengerOperator and StateSponsor identities are opaque: the
server does not compare their ``X-User-ID`` to any entity's ``id``, so a
shared constant is canonical.

HostRailroadRep identity is entity-backed: ``X-User-ID`` must equal the ``id``
of the owning ``HostRailroad``. ``make_host_rep_headers`` MUST be called with
the actual railroad id whenever the call is ownership-gated; the shared
``HOST_REP_HEADERS`` constant is a fallback for tests that never exercise
ownership (for example role-denial probes against a non-existent resource).
"""

from prd_bench_local_runner.testing import build_user_headers

SYSTEM_ADMIN_HEADERS = build_user_headers("test-system-admin-1", "SystemAdmin")
PASSENGER_OPERATOR_HEADERS = build_user_headers("test-passenger-operator-1", "PassengerOperator")
STATE_SPONSOR_HEADERS = build_user_headers("test-state-sponsor-1", "StateSponsor")
# Fallback only: never equals any real HostRailroad.id.
HOST_REP_HEADERS = build_user_headers("test-host-rep-unowned", "HostRailroadRep")

TEST_USERS = {
    "system_admin_headers": SYSTEM_ADMIN_HEADERS,
    "passenger_operator_headers": PASSENGER_OPERATOR_HEADERS,
    "state_sponsor_headers": STATE_SPONSOR_HEADERS,
    "host_rep_headers": HOST_REP_HEADERS,
}


def make_host_rep_headers(host_railroad_id: str) -> dict:
    """HostRailroadRep headers whose X-User-ID is the owning railroad's id."""
    return build_user_headers(host_railroad_id, "HostRailroadRep")
