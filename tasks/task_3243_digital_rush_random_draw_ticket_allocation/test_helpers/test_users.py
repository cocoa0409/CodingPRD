"""Pre-built role headers for every declared role.

``Patron`` is the only entity-backed role: when ``X-User-Role`` is ``Patron``,
``X-User-ID`` is the ``id`` of the acting ``Patron`` row. Every other role
presents an opaque operator identifier that is not tied to a persisted entity,
so the shared constants below are their canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # entity_backed role: the shared constant is a fallback for calls that do not
    # exercise ownership. Prefer make_patron_headers(patron["id"]).
    "patron_headers": build_user_headers("test-patron-1", "Patron"),
    "ops_manager_headers": build_user_headers("om-1", "OpsManager"),
    "allocations_coordinator_headers": build_user_headers("ac-1", "AllocationsCoordinator"),
    "customer_service_headers": build_user_headers("cs-1", "CustomerService"),
    "financial_ops_headers": build_user_headers("fo-1", "FinancialOps"),
    "concierge_desk_staff_headers": build_user_headers("cds-1", "ConciergeDeskStaff"),
    "producer_analyst_headers": build_user_headers("pa-1", "ProducerAnalyst"),
    "demand_analyst_headers": build_user_headers("da-1", "DemandAnalyst"),
    "platform_admin_headers": build_user_headers("padmin-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
}


# Per-instance builder — required because Patron is entity_backed:Patron.
def make_patron_headers(user_id: str) -> dict:
    """For Patron (entity_backed:Patron). Pass the actual Patron.id as user_id
    whenever the call compares a resource's patron foreign key to X-User-ID."""
    return build_user_headers(user_id, "Patron")


def make_ops_manager_headers(user_id: str) -> dict:
    """For OpsManager, whose recorded operator fields (released_by) are opaque."""
    return build_user_headers(user_id, "OpsManager")


def make_allocations_coordinator_headers(user_id: str) -> dict:
    """For AllocationsCoordinator, whose recorded operator field is qa_checked_by."""
    return build_user_headers(user_id, "AllocationsCoordinator")


def make_customer_service_headers(user_id: str) -> dict:
    """For CustomerService, whose recorded operator field is approved_by."""
    return build_user_headers(user_id, "CustomerService")