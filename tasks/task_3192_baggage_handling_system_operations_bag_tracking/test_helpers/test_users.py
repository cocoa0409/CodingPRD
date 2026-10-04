"""Pre-built role headers for every role in the PRD (PRD §2.1).

Seven roles are opaque: when X-User-Role is one of them, X-User-ID is an
operator identifier not tied to any persisted entity.  The Passenger role is
the exception — it is entity-backed by the Bag row's passenger_ref, so
ownership checks compare a resource's passenger_ref to X-User-ID.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — canonical for the opaque roles, and a fallback for
# non-ownership tests on the entity-backed role.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "acceptance_agent_headers": build_user_headers("test-acceptance-1", "AcceptanceAgent"),
    "sortation_agent_headers": build_user_headers("test-sortation-1", "SortationAgent"),
    "screener_headers": build_user_headers("test-screener-1", "Screener"),
    "load_agent_headers": build_user_headers("test-load-1", "LoadAgent"),
    "transfer_agent_headers": build_user_headers("test-transfer-1", "TransferAgent"),
    "baggage_service_agent_headers": build_user_headers("test-bso-1", "BaggageServiceAgent"),
    # entity_backed:Bag via passenger_ref — shared constant is a fallback only.
    "passenger_headers": build_user_headers("PNR7X2Q", "Passenger"),
}


def make_passenger_headers(passenger_ref: str) -> dict:
    """For Passenger (entity_backed:Bag via passenger_ref).

    Pass the actual bag's passenger_ref whenever the call is ownership-gated;
    the tracking lookup and per-bag reads compare it against the row's own
    passenger_ref.
    """
    return build_user_headers(passenger_ref, "Passenger")