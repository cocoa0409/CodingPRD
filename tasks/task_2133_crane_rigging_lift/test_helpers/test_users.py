"""Pre-built role headers for every role recognised by the PRD (section 2.1)."""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#
# Dispatcher, LiftDirector, SafetyManager and BillingClerk are opaque roles:
# X-User-ID is an opaque operator identifier never compared against any stored
# row, so a shared constant is the canonical form for them.
#
# Engineer, Operator and Customer are entity-backed: their X-User-ID must be a
# real Personnel / Customer id whenever the call is ownership-gated.  The
# shared constants below are a fallback for tests that do NOT exercise
# ownership (e.g. a 403-on-role test or a 404-on-missing-resource test).
TEST_USERS = {
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "lift_director_headers": build_user_headers("test-lift-director-1", "LiftDirector"),
    "safety_manager_headers": build_user_headers("test-safety-manager-1", "SafetyManager"),
    "billing_clerk_headers": build_user_headers("test-billing-clerk-1", "BillingClerk"),
    "engineer_headers": build_user_headers("test-engineer-1", "Engineer"),
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}

DISPATCHER = TEST_USERS["dispatcher_headers"]
LIFT_DIRECTOR = TEST_USERS["lift_director_headers"]
SAFETY_MANAGER = TEST_USERS["safety_manager_headers"]
BILLING_CLERK = TEST_USERS["billing_clerk_headers"]


def make_engineer_headers(personnel_id: str) -> dict:
    """For the Engineer role, whose X-User-ID is the acting Personnel row's id.

    Pass the real Personnel id whenever the call compares the caller against a
    review's author_personnel_id.
    """
    return build_user_headers(personnel_id, "Engineer")


def make_operator_headers(personnel_id: str) -> dict:
    """For the Operator role, whose X-User-ID is the acting Personnel row's id.

    Pass the plan's operator_id whenever the call drives the operational
    dimension of that plan.
    """
    return build_user_headers(personnel_id, "Operator")


def make_customer_headers(customer_id: str) -> dict:
    """For the Customer role, whose X-User-ID is the acting Customer row's id."""
    return build_user_headers(customer_id, "Customer")


def make_headers(user_id: str, role: str) -> dict:
    """Escape hatch for tests that need an arbitrary id/role pair."""
    return build_user_headers(user_id, role)
