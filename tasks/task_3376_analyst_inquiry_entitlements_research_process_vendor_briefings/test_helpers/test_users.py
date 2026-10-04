"""Pre-built role headers for every role the API recognizes.

Roles whose `X-User-ID` is an opaque operator identifier use the shared
constants below.  Roles whose identity is backed by a persisted entity
(`ClientAdmin` -> ClientAccount, `SeatHolder` -> Seat, `Analyst` -> Analyst,
`VendorRep` -> Vendor) must use the per-instance builders whenever the call
they make is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for calls that do not depend on
# the caller owning the subject resource.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "research_director_headers": build_user_headers("test-research-director-1", "ResearchDirector"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "event_programmer_headers": build_user_headers("test-event-programmer-1", "EventProgrammer"),
    "sales_rep_headers": build_user_headers("test-sales-rep-1", "SalesRep"),
    # Entity-backed roles: the shared constant is a fallback for tests that do
    # not exercise ownership only.
    "client_admin_headers": build_user_headers("test-client-admin-1", "ClientAdmin"),
    "seat_holder_headers": build_user_headers("test-seat-holder-1", "SeatHolder"),
    "analyst_headers": build_user_headers("test-analyst-1", "Analyst"),
    "vendor_rep_headers": build_user_headers("test-vendor-rep-1", "VendorRep"),
}


# ─── Per-instance builders (mandatory for entity-backed roles) ────────────

def make_client_admin_headers(account_id: str) -> dict:
    """ClientAdmin acts as a ClientAccount; pass that account's id."""
    return build_user_headers(account_id, "ClientAdmin")


def make_seat_holder_headers(seat_id: str) -> dict:
    """SeatHolder acts as a Seat; pass that seat's id."""
    return build_user_headers(seat_id, "SeatHolder")


def make_analyst_headers(analyst_id: str) -> dict:
    """Analyst acts as an Analyst; pass that analyst's id."""
    return build_user_headers(analyst_id, "Analyst")


def make_vendor_rep_headers(vendor_id: str) -> dict:
    """VendorRep acts as a Vendor; pass that vendor's id."""
    return build_user_headers(vendor_id, "VendorRep")
