"""Pre-built role headers for every role in the PRD.

Dispatcher, FlightDeptManager, MaintenancePlanner, and FinanceAdmin are opaque
identities: X-User-ID is not tied to any persisted entity. ExecutiveRequester
is entity-backed by PassengerProfile (X-User-ID is the acting passenger's id);
ownership-gated calls (trip creation, submit, leg creation by the requester)
MUST use make_executive_requester_headers() with the real PassengerProfile id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "dispatcher_headers": build_user_headers("disp-shared-1", "Dispatcher"),
    "manager_headers": build_user_headers("mgr-shared-1", "FlightDeptManager"),
    "planner_headers": build_user_headers("planner-shared-1", "MaintenancePlanner"),
    "finance_headers": build_user_headers("fin-shared-1", "FinanceAdmin"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "executive_headers": build_user_headers("exec-shared-1", "ExecutiveRequester"),
}


def make_dispatcher_headers(user_id: str) -> dict:
    """Dispatcher is opaque; distinct user ids matter for segregation-of-duties
    checks (assign vs dispatch on personal-use trips)."""
    return build_user_headers(user_id, "Dispatcher")


def make_manager_headers(user_id: str = "mgr-shared-1") -> dict:
    return build_user_headers(user_id, "FlightDeptManager")


def make_planner_headers(user_id: str = "planner-shared-1") -> dict:
    return build_user_headers(user_id, "MaintenancePlanner")


def make_finance_headers(user_id: str) -> dict:
    """FinanceAdmin is opaque; a distinct user id matters for the settle-time
    segregation-of-duties check against personal_use_approved_by."""
    return build_user_headers(user_id, "FinanceAdmin")


def make_executive_requester_headers(passenger_profile_id: str) -> dict:
    """For ExecutiveRequester (entity_backed:PassengerProfile). Pass the acting
    PassengerProfile.id whenever the call is ownership-gated."""
    return build_user_headers(passenger_profile_id, "ExecutiveRequester")
