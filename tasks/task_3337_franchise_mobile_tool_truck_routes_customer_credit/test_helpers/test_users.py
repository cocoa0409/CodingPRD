"""Pre-built role headers for the seven roles the service recognises."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the opaque operator roles, and for calls whose
# outcome does not depend on the caller owning the subject resource.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "franchise_manager_headers": build_user_headers("test-franchise-manager-1",
                                                    "FranchiseManager"),
    "credit_officer_headers": build_user_headers("test-credit-officer-1", "CreditOfficer"),
    "warranty_admin_headers": build_user_headers("test-warranty-admin-1", "WarrantyAdmin"),
    # entity-backed roles: the shared constants are fallbacks for calls that are
    # not ownership-gated. Ownership-gated calls must use the builders below.
    "franchise_owner_headers": build_user_headers("test-franchise-owner-1", "FranchiseOwner"),
    "route_sales_rep_headers": build_user_headers("test-routesalesrep-1", "RouteSalesRep"),
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    # Deliberately unrecognised role name — used for the user-context check.
    "unknown_role_headers": build_user_headers("test-unknown-1", "UnknownRole"),
}


def make_franchise_owner_headers(franchisee_id: str) -> dict:
    """FranchiseOwner is entity-backed to Franchisee: pass the acting
    Franchisee's id whenever the call is ownership-gated."""
    return build_user_headers(franchisee_id, "FranchiseOwner")


def make_route_sales_rep_headers(franchisee_id: str) -> dict:
    """RouteSalesRep is entity-backed to Franchisee: pass the acting
    Franchisee's id whenever the call is ownership-gated."""
    return build_user_headers(franchisee_id, "RouteSalesRep")


def make_technician_headers(technician_id: str) -> dict:
    """Technician is entity-backed to Technician: pass the acting Technician's
    id whenever the call is ownership-gated."""
    return build_user_headers(technician_id, "Technician")


def headers_without_user_context() -> dict:
    """No identity headers at all — used for the missing-context check."""
    return {"Content-Type": "application/json"}
