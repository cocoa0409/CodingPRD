"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles (X-User-ID is never compared
# against an entity id for these), and for CustomerRep tests that do not
# exercise ownership (e.g. 4xx-on-bad-request paths).
TEST_USERS = {
    "operator_headers": build_user_headers("op-0", "TerminalOperator"),
    "commercial_headers": build_user_headers("cm-0", "CommercialManager"),
    "gas_headers": build_user_headers("gs-0", "GasScheduler"),
    "marine_headers": build_user_headers("ms-0", "MarineScheduler"),
    # Fallback only — for entity_backed ownership tests always use
    # make_customer_rep_headers(customer["id"]) instead.
    "customer_rep_headers": build_user_headers("test-customer-rep-1", "CustomerRep"),
}

# A header pair with no auth headers at all, used by unauthenticated tests.
NO_HEADERS: dict = {}


def make_customer_rep_headers(customer_id: str) -> dict:
    """For CustomerRep (entity_backed:Customer). Pass the actual Customer.id
    whenever the call is ownership-gated (confirm, nomination, cancellation,
    tender-nor, laytime agree/dispute)."""
    return build_user_headers(customer_id, "CustomerRep")


def make_operator_headers(user_id: str) -> dict:
    """For TerminalOperator (opaque identity). Use distinct user ids to
    exercise the turnaround segregation-of-duties rule."""
    return build_user_headers(user_id, "TerminalOperator")
