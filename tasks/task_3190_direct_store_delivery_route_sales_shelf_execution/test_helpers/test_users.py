"""Pre-built role headers for every role in the PRD (§2.1).

PlatformAdmin and RouteSupervisor are opaque roles: their X-User-ID is not
compared against any entity id, so shared constants are safe.

RouteSalesRep and StoreManager are entity-backed roles: X-User-ID must equal
the acting RouteSalesRepresentative.id / Store.id whenever the call is
ownership-gated. Use make_rep_headers(rep["id"]) /
make_store_manager_headers(store["id"]) for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for non-ownership tests.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "supervisor_headers": build_user_headers("sup-1", "RouteSupervisor"),
    "supervisor2_headers": build_user_headers("sup-2", "RouteSupervisor"),
    # Fallback for non-ownership-gated calls only; never use for
    # rep-owned or store-scoped operations.
    "rep_headers": build_user_headers("test-rep-1", "RouteSalesRep"),
    "store_manager_headers": build_user_headers("test-store-mgr-1", "StoreManager"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """PlatformAdmin (opaque identity)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_supervisor_headers(user_id: str = "sup-1") -> dict:
    """RouteSupervisor (opaque identity). Use a distinct user_id when
    segregation of duties requires a second supervisor."""
    return build_user_headers(user_id, "RouteSupervisor")


def make_rep_headers(user_id: str) -> dict:
    """RouteSalesRep (entity-backed: RouteSalesRepresentative). Pass the actual
    rep id whenever the call is ownership-gated (load/start/dispute, etc.)."""
    return build_user_headers(user_id, "RouteSalesRep")


def make_store_manager_headers(user_id: str) -> dict:
    """StoreManager (entity-backed: Store). Pass the actual store id whenever
    the call is store-scoped (shelf/promo verification)."""
    return build_user_headers(user_id, "StoreManager")
