"""Pre-built role headers for the five roles the PRD declares (§2.1).

Four of the five roles carry an opaque operator identifier in `X-User-ID`; only
`SupplierRep` is entity-backed, where `X-User-ID` must be the acting Supplier's `id`.
Ownership-gated SupplierRep calls MUST use make_supplier_rep_headers(supplier_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers. Two distinct BuyoutManager operators exist because
# segregation of duties is enforced within that role by X-User-ID.
BUYOUT_MANAGER_ID = "op-buyout-manager-1"
BUYOUT_MANAGER_2_ID = "op-buyout-manager-2"
PROJECT_EXECUTIVE_ID = "op-project-executive-1"
DESIGN_ENGINEER_ID = "op-design-engineer-1"
OWNER_REP_ID = "op-owner-rep-1"

# A SupplierRep identifier that is deliberately not any real Supplier.id — for tests
# that do not exercise ownership (401/403/404/422 paths) or that assert a scope violation.
UNKNOWN_SUPPLIER_REP_ID = "11111111-2222-4333-8444-555555555555"

TEST_USERS = {
    "buyout_manager_headers": build_user_headers(BUYOUT_MANAGER_ID, "BuyoutManager"),
    "buyout_manager_2_headers": build_user_headers(BUYOUT_MANAGER_2_ID, "BuyoutManager"),
    "project_executive_headers": build_user_headers(
        PROJECT_EXECUTIVE_ID, "ProjectExecutive"
    ),
    "design_engineer_headers": build_user_headers(DESIGN_ENGINEER_ID, "DesignEngineer"),
    "owner_rep_headers": build_user_headers(OWNER_REP_ID, "OwnerRep"),
    # Fallback SupplierRep constant — only for tests that do not depend on the caller
    # owning the subject resource.
    "supplier_rep_headers": build_user_headers(UNKNOWN_SUPPLIER_REP_ID, "SupplierRep"),
}


def make_supplier_rep_headers(supplier_id: str) -> dict:
    """Headers for a SupplierRep acting for the Supplier whose id is `supplier_id`.

    Mandatory for every ownership-gated call: submitting a quote, revising a quote,
    countering escalation terms, and filing a storage document.
    """
    return build_user_headers(supplier_id, "SupplierRep")


def make_buyout_manager_headers(user_id: str) -> dict:
    """Headers for a specific BuyoutManager operator (segregation-of-duties tests)."""
    return build_user_headers(user_id, "BuyoutManager")


def make_project_executive_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProjectExecutive")


def make_design_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DesignEngineer")


def make_owner_rep_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OwnerRep")


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary header pair — for authentication tests that need odd values.

    A blank header must be passed as the empty string, never as whitespace.
    """
    return build_user_headers(user_id, role)


ALL_ROLES = [
    "BuyoutManager",
    "SupplierRep",
    "ProjectExecutive",
    "DesignEngineer",
    "OwnerRep",
]
