"""Pre-built role headers for the three roles declared in the PRD (2.1).

FranchiseAdmin and ComplianceAuditor are opaque-operator roles: X-User-ID is an
identifier not tied to any persisted entity, so the shared constant is the
canonical form. FranchiseeOperator is entity_backed by Franchisee: X-User-ID
must be the acting Franchisee's id wherever the call is ownership-gated, so the
per-instance builder make_franchisee_operator_headers(franchisee_id) is used
for every such call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "franchise_admin_headers": build_user_headers("test-franchise-admin-1", "FranchiseAdmin"),
    # opaque role: shared constant is the canonical form.
    "compliance_auditor_headers": build_user_headers(
        "test-compliance-auditor-1", "ComplianceAuditor",
    ),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "franchisee_operator_headers": build_user_headers(
        "test-franchisee-operator-1", "FranchiseeOperator",
    ),
}


def make_franchise_admin_headers(user_id: str) -> dict:
    """FranchiseAdmin is opaque — user_id is recorded, never compared to an id."""
    return build_user_headers(user_id, "FranchiseAdmin")


def make_compliance_auditor_headers(user_id: str) -> dict:
    """ComplianceAuditor is opaque — user_id is recorded, never compared to an id."""
    return build_user_headers(user_id, "ComplianceAuditor")


def make_franchisee_operator_headers(franchisee_id: str) -> dict:
    """FranchiseeOperator is entity_backed:Franchisee. Pass the acting
    Franchisee.id whenever the call is ownership-gated (dispatch, complete,
    renew, accept, decline, dispute, request-expansion, release, withdraw)."""
    return build_user_headers(franchisee_id, "FranchiseeOperator")