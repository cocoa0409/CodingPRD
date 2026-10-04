"""Pre-built role headers for the three PRD §2.1 roles.

Identity model (PRD §2.1):
- ManufacturerAdmin: X-User-ID is an opaque operator identifier, never
  compared to an entity id — the shared constant is canonical.
- DealerRep: X-User-ID IS the acting Dealer's id; ownership-gated calls MUST
  use make_dealer_headers(dealer["id"]) — the shared constant never matches a
  real dealer id and exists only for tests that do not exercise ownership
  (e.g. 400-on-bad-payload before any resource exists).
- EndUserRep: X-User-ID IS the acting EndUser's id; same rule via
  make_end_user_headers(end_user["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: canonical shared constant.
    "admin_headers": build_user_headers("test-admin-1", "ManufacturerAdmin"),
    # Entity-backed fallbacks — NON-OWNERSHIP TESTS ONLY. Never pass these to
    # a call whose success depends on owning the resource.
    "dealer_headers": build_user_headers("test-dealer-unbound-1", "DealerRep"),
    "end_user_headers": build_user_headers("test-enduser-unbound-1", "EndUserRep"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """ManufacturerAdmin headers; user_id is opaque (PRD §2.1)."""
    return build_user_headers(user_id, "ManufacturerAdmin")


def make_dealer_headers(dealer_id: str) -> dict:
    """DealerRep headers bound to a real Dealer.id (PRD §2.1: ownership
    compares the resource's dealer_id to X-User-ID)."""
    return build_user_headers(dealer_id, "DealerRep")


def make_end_user_headers(end_user_id: str) -> dict:
    """EndUserRep headers bound to a real EndUser.id (PRD §2.1: ownership
    compares the order's agreement's end_user_id to X-User-ID)."""
    return build_user_headers(end_user_id, "EndUserRep")
