"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "sourcing_headers": build_user_headers("test-sourcing-1", "SourcingManager"),
    "crewops_headers": build_user_headers("test-crewops-1", "CrewOps"),
    "finance_headers": build_user_headers("test-finance-1", "FinanceAnalyst"),
    "auditor_headers": build_user_headers("test-auditor-1", "CrewAuditor"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "vendor_rep_headers": build_user_headers("test-vendor-1", "HotelVendorRep"),
}


# Per-instance builder — required for the entity_backed role HotelVendorRep.
def make_vendor_rep_headers(vendor_id: str) -> dict:
    """For HotelVendorRep (entity_backed:HotelVendor). Pass the actual HotelVendor.id
    as vendor_id whenever the call is ownership-gated (proposal submission/withdrawal,
    invoice submission, allocation check-in)."""
    return build_user_headers(vendor_id, "HotelVendorRep")
