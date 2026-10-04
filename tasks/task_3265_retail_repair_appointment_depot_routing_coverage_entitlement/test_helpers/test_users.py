"""Pre-built role headers for every role in the PRD.

Identity semantics differ by role (PRD §2.1):
- Customer / Technician are entity-backed: X-User-ID must be the acting
  Customer/Technician record's id. Use the per-instance builders for any
  ownership-gated call.
- Anonymous / CustomerService / DepotAgent / PlatformAdmin use opaque
  operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "customer_headers": build_user_headers("customer-shared-1", "Customer"),
    "technician_headers": build_user_headers("technician-shared-1", "Technician"),
    "customer_service_headers": build_user_headers("cs-1", "CustomerService"),
    "depot_agent_headers": build_user_headers("depot-1", "DepotAgent"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For the entity-backed Customer role. Pass the actual Customer.id as
    customer_id whenever the call is ownership-gated."""
    return build_user_headers(customer_id, "Customer")


def make_technician_headers(technician_id: str) -> dict:
    """For the entity-backed Technician role. Pass the actual Technician.id as
    technician_id whenever the call ties the technician to a location."""
    return build_user_headers(technician_id, "Technician")


def make_anonymous_headers(user_id: str = "anon-1") -> dict:
    return build_user_headers(user_id, "Anonymous")


def make_customer_service_headers(user_id: str = "cs-1") -> dict:
    return build_user_headers(user_id, "CustomerService")


def make_depot_agent_headers(user_id: str = "depot-1") -> dict:
    return build_user_headers(user_id, "DepotAgent")


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
