"""Pre-built role headers for every role in the authorization matrix.

Six of the seven roles are opaque operator identities, so a shared constant is
the canonical form for them. The seventh role, ``Buyer``, is entity-backed: its
``X-User-ID`` must be the id of a real ``Buyer`` row, so the per-instance
builder below is mandatory on every ownership-gated or buyer-scoped call.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("op-admin-1", "PlatformAdmin"),
    "compliance_officer_headers": build_user_headers("op-compliance-1", "ComplianceOfficer"),
    "sales_counselor_headers": build_user_headers("op-sales-1", "SalesCounselor"),
    "mortgage_banker_headers": build_user_headers("op-banker-1", "MortgageBanker"),
    "closing_officer_headers": build_user_headers("op-closing-1", "ClosingOfficer"),
    "anonymous_headers": build_user_headers("op-anonymous-1", "Anonymous"),
}

# Friendly aliases used by the fixtures and tests.
ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]
COMPLIANCE_HEADERS = TEST_USERS["compliance_officer_headers"]
SALES_HEADERS = TEST_USERS["sales_counselor_headers"]
BANKER_HEADERS = TEST_USERS["mortgage_banker_headers"]
CLOSING_HEADERS = TEST_USERS["closing_officer_headers"]
ANONYMOUS_HEADERS = TEST_USERS["anonymous_headers"]


def make_buyer_headers(buyer_id: str) -> dict:
    """Headers for the entity-backed Buyer role.

    Pass the real ``Buyer.id`` as ``buyer_id`` on every call that is
    ownership-gated - acknowledging a disclosure, or reading a contract,
    allocation, application, disclosure or lock that belongs to that buyer.
    """
    return build_user_headers(buyer_id, "Buyer")


def headers_without_role(user_id: str = "op-roleless-1") -> dict:
    """A caller that supplies an identity but no role - used for the 401 rung."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_unknown_role(role: str = "NotARole", user_id: str = "op-unknown-1") -> dict:
    """A caller whose role string matches nothing in the matrix."""
    return build_user_headers(user_id, role)