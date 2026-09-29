"""Pre-built role headers for the six roles of PRD 2.1.

For PlatformAdmin, TreasuryOfficer, BranchManager, BranchTeller and
ComplianceOfficer the X-User-ID is an opaque operator identifier that is never
compared to any row id, so a shared constant is the canonical form.

For Customer, X-User-ID is the id of the acting customer row, so the shared
constant is only a fallback for calls that are not ownership-gated; anything that
reads on a customer's behalf must be built with make_customer_headers(customer_id).
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import OPERATORS

TEST_USERS = {
    "admin_headers": build_user_headers(OPERATORS["ADMIN"], "PlatformAdmin"),
    "treasury_headers": build_user_headers(OPERATORS["TREASURY"], "TreasuryOfficer"),
    "manager_headers": build_user_headers(OPERATORS["MANAGER"], "BranchManager"),
    "teller_headers": build_user_headers(OPERATORS["TELLER_1"], "BranchTeller"),
    "teller2_headers": build_user_headers(OPERATORS["TELLER_2"], "BranchTeller"),
    "compliance_headers": build_user_headers(OPERATORS["COMPLIANCE"], "ComplianceOfficer"),
    # Customer is entity_backed: this shared constant is a deliberate non-owner.
    "customer_headers": build_user_headers("not-a-real-customer-row", "Customer"),
}


def make_admin_headers(user_id: str) -> dict:
    """PlatformAdmin acting as a named operator (opaque X-User-ID)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_treasury_headers(user_id: str) -> dict:
    """TreasuryOfficer acting as a named operator (opaque X-User-ID)."""
    return build_user_headers(user_id, "TreasuryOfficer")


def make_manager_headers(user_id: str) -> dict:
    """BranchManager acting as a named operator (opaque X-User-ID)."""
    return build_user_headers(user_id, "BranchManager")


def make_teller_headers(user_id: str) -> dict:
    """BranchTeller acting as a named operator (opaque X-User-ID)."""
    return build_user_headers(user_id, "BranchTeller")


def make_compliance_headers(user_id: str) -> dict:
    """ComplianceOfficer acting as a named operator (opaque X-User-ID)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_customer_headers(customer_id: str) -> dict:
    """Customer role headers.  Pass the real Customer row id: PRD 2.1 makes
    X-User-ID the id of the acting customer for this role."""
    return build_user_headers(customer_id, "Customer")


def headers_without_role(user_id: str = "anyone") -> dict:
    """A request that omits X-User-Role entirely (PRD 2.8 rank 1)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = "PlatformAdmin") -> dict:
    """A request that omits X-User-ID entirely (PRD 2.8 rank 1)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = "auditor-01", role: str = "Auditor") -> dict:
    """A request declaring a role name outside the six the PRD lists."""
    return build_user_headers(user_id, role)
