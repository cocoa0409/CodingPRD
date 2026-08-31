"""Pre-built role headers for every role in the PRD.

`ClearinghouseOperator` is an opaque principal: its `X-User-ID` is never compared
to any stored row, so the shared constant is the canonical form.  The other three
roles carry the acting `Carrier.id` in `X-User-ID`, so every ownership-gated call
must use the per-instance builder with the real carrier id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants.  Safe for the opaque operator role and for tests whose outcome
# does not depend on the caller owning the subject resource (401/403/404 paths).
TEST_USERS = {
    "operator_headers": build_user_headers("clearinghouse-operator-1", "ClearinghouseOperator"),
    "accountant_headers": build_user_headers("test-accountant-1", "RevenueAccountant"),
    "billing_agent_headers": build_user_headers("test-billing-agent-1", "BillingAgent"),
    "auditor_headers": build_user_headers("test-auditor-1", "InterlineAuditor"),
}

OPERATOR = TEST_USERS["operator_headers"]


def make_operator_headers(user_id="clearinghouse-operator-1"):
    """ClearinghouseOperator identity is opaque; the id is never matched to a row."""
    return build_user_headers(user_id, "ClearinghouseOperator")


def make_accountant_headers(carrier_id):
    """RevenueAccountant of one carrier. Pass the acting Carrier.id."""
    return build_user_headers(carrier_id, "RevenueAccountant")


def make_billing_agent_headers(carrier_id):
    """BillingAgent of one carrier. Pass the acting Carrier.id."""
    return build_user_headers(carrier_id, "BillingAgent")


def make_auditor_headers(carrier_id):
    """InterlineAuditor of one carrier. Pass the acting Carrier.id."""
    return build_user_headers(carrier_id, "InterlineAuditor")


def make_headers(role, user_id):
    """Generic builder used by parametrized role tests."""
    return build_user_headers(user_id, role)


ANONYMOUS_HEADERS = {"Content-Type": "application/json"}
